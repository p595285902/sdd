"""Protected acceptance reset coordination. Docker ownership stays in the controller."""
import hmac
import json
import os
import stat
import threading
import uuid
from pathlib import Path
from time import monotonic
from typing import Any, Literal

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlmodel import Session, SQLModel, select

from app.core.config import Settings, settings
from app.core.security import get_password_hash, verify_password
from app.models import User
from app.services.acceptance_work import WorkBarrier

OWNER_FILE = ".acceptance-owner.json"


class ControlError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code


def reset_enabled(configuration: Settings = settings) -> bool:
    return configuration.DEVELOP_ACCEPTANCE_MODE and configuration.DEVELOP_ACCEPTANCE_RESET_ENABLED


def confined_environment(source: dict[str, str]) -> dict[str, str]:
    if not reset_enabled():
        return source
    root = settings.ACCEPTANCE_AGENT_ROOT
    # No inherited scenario/global CLI config or temporary directory may escape.
    result = dict(source)
    for key in ("ACCEPTANCE_RESET_TOKEN", "SECRET_KEY", "DATABASE_URL", "FIRST_SUPERUSER_PASSWORD", "OPENCODE_CONFIG", "OPENCODE_CONFIG_CONTENT", "OPENCODE_CONFIG_DIR"):
        result.pop(key, None)
    for key, child in {
        "HOME": "home", "XDG_DATA_HOME": "data", "XDG_CONFIG_HOME": "config",
        "XDG_CACHE_HOME": "cache", "XDG_STATE_HOME": "state",
        "XDG_RUNTIME_DIR": "runtime", "TMPDIR": "tmp",
    }.items():
        path = root / child
        if root.is_symlink() or path.is_symlink():
            raise RuntimeError("Unsafe acceptance agent storage")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        result[key] = str(path)
    return result


def _schema_snapshot(database: Engine) -> tuple[Any, Any]:
    inspector = inspect(database)
    tables = inspector.get_table_names()
    schema = [(name, inspector.get_columns(name), inspector.get_foreign_keys(name), inspector.get_indexes(name)) for name in tables]
    # Type objects have stable representations, not equality across inspection instances.
    signature = repr(schema)
    with database.connect() as connection:
        versions = tuple(connection.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).scalars()) if "alembic_version" in tables else ()
    return signature, versions


def restore_database(database: Engine, configuration: Settings, deadline: float) -> tuple[Any, Any]:
    snapshot = _schema_snapshot(database)
    with Session(database) as session, session.begin():
        connection = session.connection()
        if database.dialect.name == "postgresql":
            milliseconds = max(1, int((deadline - monotonic()) * 1000))
            connection.execute(text("SELECT set_config('statement_timeout', :timeout, true)"), {"timeout": str(milliseconds)})
            connection.execute(text("SELECT set_config('lock_timeout', :timeout, true)"), {"timeout": str(milliseconds)})
            actual = connection.execute(text("SELECT current_database()")).scalar_one()
            if actual != "app":
                raise RuntimeError("Acceptance database identity mismatch")
        for table in reversed(SQLModel.metadata.sorted_tables):
            connection.execute(table.delete())
        # Do not use CRUD helpers: they commit and would break rollback atomicity.
        session.add(User(
            email=configuration.FIRST_SUPERUSER,
            hashed_password=get_password_hash(configuration.FIRST_SUPERUSER_PASSWORD),
            is_active=True, is_superuser=True, full_name=None,
            concurrent_agent_turn_limit=configuration.DEVELOP_USER_CONCURRENT_TURN_LIMIT_DEFAULT,
        ))
        session.flush()
        if monotonic() >= deadline:
            raise TimeoutError("Database reset deadline exceeded")
    return snapshot


def verify_database(database: Engine, configuration: Settings, snapshot: tuple[Any, Any]) -> None:
    if _schema_snapshot(database) != snapshot:
        raise RuntimeError("Database schema or migration metadata changed")
    with Session(database) as session:
        users = session.exec(select(User)).all()
        if len(users) != 1:
            raise RuntimeError("Database administrator baseline mismatch")
        user = users[0]
        if not (user.email == configuration.FIRST_SUPERUSER and user.is_active and user.is_superuser and user.full_name is None and user.concurrent_agent_turn_limit == configuration.DEVELOP_USER_CONCURRENT_TURN_LIMIT_DEFAULT and verify_password(configuration.FIRST_SUPERUSER_PASSWORD, user.hashed_password)[0]):
            raise RuntimeError("Database administrator baseline mismatch")
        for table in SQLModel.metadata.sorted_tables:
            if table.name != User.__tablename__ and session.connection().execute(table.select().limit(1)).first() is not None:
                raise RuntimeError("Mutable database records remain")


class OwnedStorage:
    def __init__(self, root: Path, run_id: str) -> None:
        self.root, self.run_id = root, run_id
        self.identity: tuple[int, int] | None = None

    def validate(self) -> None:
        if not self.root.is_absolute() or self.root.is_symlink() or self.root.resolve() != self.root or not self.root.is_dir():
            raise RuntimeError("Unsafe acceptance storage root")
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            identity = (info.st_dev, info.st_ino)
            if self.identity is not None and self.identity != identity:
                raise RuntimeError("Acceptance storage identity changed")
            expected = {"run_id": self.run_id}
            try:
                marker = os.open(OWNER_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            except FileNotFoundError:
                marker = os.open(OWNER_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
                with os.fdopen(marker, "w") as handle:
                    json.dump(expected, handle)
            except OSError:
                raise RuntimeError("Unsafe acceptance ownership marker") from None
            else:
                with os.fdopen(marker) as handle:
                    if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                        raise RuntimeError("Unsafe acceptance ownership marker")
                    contents = handle.read(1025)
                    if len(contents) > 1024 or json.loads(contents) != expected:
                        raise RuntimeError("Acceptance storage owner mismatch")
            self.identity = identity
        finally:
            os.close(descriptor)

    def clean(self, deadline: float) -> None:
        import shutil

        self.validate()
        if not shutil.rmtree.avoids_symlink_attacks:
            raise RuntimeError("Safe descriptor-relative cleanup is unavailable")
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != self.identity:
                raise RuntimeError("Acceptance storage changed before cleanup")
            for name in os.listdir(descriptor):
                if monotonic() >= deadline:
                    raise TimeoutError("Storage cleanup deadline exceeded")
                if name == OWNER_FILE:
                    continue
                # lstat and fd-relative rmtree refuse links; unlink never follows them.
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    shutil.rmtree(name, dir_fd=descriptor)
                else:
                    os.unlink(name, dir_fd=descriptor)
        finally:
            os.close(descriptor)
        self.verify()

    def verify(self) -> None:
        self.validate()
        if set(os.listdir(self.root)) != {OWNER_FILE}:
            raise RuntimeError("Acceptance storage baseline mismatch")


class AcceptanceResetCoordinator:
    def __init__(self, configuration: Settings = settings, *, barrier: WorkBarrier | None = None) -> None:
        self.settings = configuration
        self.barrier = barrier or WorkBarrier()
        self.boot_id = uuid.uuid4().hex
        self.phase = "admitting"
        self.failure_phase: str | None = None
        self._phase_started: float | None = None
        self._phase_timings: list[dict[str, Any]] = []
        self.baseline_verified = False
        self._baseline_activity = -1
        self.configuration: Literal["available", "unavailable"] = "available" if configuration.DEMO_GITHUB_REPO and configuration.DEMO_GITHUB_TOKEN else "unavailable"
        self.baseline_configuration = self.configuration
        self._repository = configuration.DEMO_GITHUB_REPO
        self._token = configuration.DEMO_GITHUB_TOKEN
        self._timing = (configuration.DEVELOP_TURN_TIMEOUT_SECONDS, configuration.DEVELOP_TURN_PRESENCE_GRACE_SECONDS)
        self._lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._ownership: dict[str, Any] | None = None
        self._controller_boot: str | None = None
        self._cached: tuple[str, int, int, dict[str, Any]] | None = None
        self._used_reset_ids: set[str] = set()
        self._operation: threading.Thread | None = None
        self.workspace = OwnedStorage(configuration.DEVELOP_WORKSPACE_ROOT, configuration.ACCEPTANCE_RUN_ID)
        self.agent = OwnedStorage(configuration.ACCEPTANCE_AGENT_ROOT, configuration.ACCEPTANCE_RUN_ID)

    def authenticate(self, authorization: str | None, run_id: str | None) -> None:
        secret = self.settings.ACCEPTANCE_RESET_TOKEN
        if not reset_enabled(self.settings):
            raise ControlError(404, "Not found")
        if secret is None or not hmac.compare_digest((authorization or "").encode(), ("Bearer " + secret.get_secret_value()).encode()):
            raise ControlError(401, "Acceptance authentication required")
        if run_id != self.settings.ACCEPTANCE_RUN_ID:
            raise ControlError(409, "Acceptance run identity mismatch")

    def repository(self) -> tuple[Any, Any]:
        return (self._repository, self._token) if self.configuration == "available" else (None, None)

    def state(self) -> dict[str, Any]:
        with self._state_lock:
            result = {
                "run_id": self.settings.ACCEPTANCE_RUN_ID,
                "generation": self.barrier.generation, "phase": self.phase,
                "configuration": self.configuration, "boot_id": self.boot_id,
                "baseline_verified": self.baseline_verified and self.barrier.activity == self._baseline_activity,
                "active_work": self.barrier.counts(),
                "phases": [dict(entry) for entry in self._phase_timings],
                "timing": {
                    "timeout_seconds": self.settings.DEVELOP_TURN_TIMEOUT_SECONDS,
                    "grace_seconds": self.settings.DEVELOP_TURN_PRESENCE_GRACE_SECONDS,
                },
            }
            if self.failure_phase:
                result["failure_phase"] = self.failure_phase
            return result

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - monotonic()
        if remaining <= 0 or self.phase == "failed":
            raise TimeoutError("Acceptance control deadline exceeded")
        return remaining

    def _finish_phase(self) -> None:
        if self._phase_started is not None:
            self._phase_timings.append({"phase": self.phase, "milliseconds": (monotonic() - self._phase_started) * 1000})
            self._phase_started = None

    def _phase(self, phase: str, deadline: float) -> None:
        with self._state_lock:
            self._remaining(deadline)
            self._finish_phase()
            self.phase = phase
            self._phase_started = monotonic()

    def _validate_ownership(self, controller: Any, database: Engine, deadline: float) -> None:
        url = make_url(str(self.settings.DATABASE_URL))
        if (url.host, url.database) != ("db", "app") or url.port not in (None, 5432) or url.query or database.url != url:
            raise RuntimeError("Fixed acceptance database scope mismatch")
        if self.settings.DEVELOP_WORKSPACE_ROOT != Path("/develop-workspaces") or self.settings.ACCEPTANCE_AGENT_ROOT != Path("/acceptance-agent-state"):
            raise RuntimeError("Fixed acceptance storage scope mismatch")
        state = controller.acceptance_state(timeout_seconds=self._remaining(deadline))
        run = self.settings.ACCEPTANCE_RUN_ID
        owned = state.get("ownership", {})
        if state.get("run_id") != run or state.get("generation") != self.barrier.generation or not state.get("boot_id"):
            raise RuntimeError("Controller run/generation identity mismatch")
        if owned.get("verified") is not True or owned.get("project") != run:
            raise RuntimeError("Controller ownership is not attested")
        db = owned.get("database", {})
        if db.get("service") != "db" or db.get("database") != "app" or db.get("compose_project") != run:
            raise RuntimeError("Database ownership is not attested")
        for key, destination in (("workspace", "/develop-workspaces"), ("agent", "/acceptance-agent-state")):
            mount = owned.get(key, {})
            if mount.get("destination") != destination or mount.get("compose_project") != run or not mount.get("volume"):
                raise RuntimeError("Storage ownership is not attested")
        services = owned.get("services", {})
        if set(services) != {"backend", "db", "preview_controller"} or any(not isinstance(value, str) or not value for value in services.values()):
            raise RuntimeError("Service identities are not attested")
        if self._ownership is not None and (owned != self._ownership or state["boot_id"] != self._controller_boot):
            raise RuntimeError("Acceptance service/storage identity changed")
        self._ownership = json.loads(json.dumps(owned))
        self._controller_boot = state["boot_id"]
        self.workspace.validate()
        self.agent.validate()

    def _controller(self, controller: Any, action: str, reset_id: str, expected: int, deadline: float, **extra: Any) -> dict[str, Any]:
        result = controller.acceptance_control(action, run_id=self.settings.ACCEPTANCE_RUN_ID, reset_id=reset_id, expected_generation=expected, timeout_seconds=self._remaining(deadline), **extra)
        if result.get("run_id") != self.settings.ACCEPTANCE_RUN_ID or result.get("boot_id") != self._controller_boot or result.get("active_work"):
            raise RuntimeError("Controller completion/identity verification failed")
        if action in ("quiesce", "reset") and (result.get("generation") != expected or result.get("phase") != ("quiesced" if action == "quiesce" else "preview_reset")):
            raise RuntimeError("Controller did not verify closed completion")
        return result

    def _drain(self, deadline: float) -> None:
        from app.services.develop_turns import develop_turn_manager

        self.barrier.close()
        self._phase("quiescing", deadline)
        develop_turn_manager.cancel_all()
        self.barrier.drain(deadline)
        develop_turn_manager.drain(deadline)

    def _restore_controls(self) -> None:
        from app.api.routes.testing_agent import fake_llm_state

        fake_llm_state.configure([])
        self.settings.DEVELOP_TURN_TIMEOUT_SECONDS, self.settings.DEVELOP_TURN_PRESENCE_GRACE_SECONDS = self._timing
        self.configuration = self.baseline_configuration

    def _verify_controls(self) -> None:
        from app.api.routes.testing_agent import fake_llm_state

        if not fake_llm_state.baseline_verified() or self.configuration != self.baseline_configuration or (self.settings.DEVELOP_TURN_TIMEOUT_SECONDS, self.settings.DEVELOP_TURN_PRESENCE_GRACE_SECONDS) != self._timing or self.barrier.counts():
            raise RuntimeError("Acceptance runtime baseline mismatch")

    def operate(self, *, reset_id: str, expected_generation: int, controller: Any, database: Engine, mode: Literal["available", "unavailable"] | None = None) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            raise ControlError(409, "Another acceptance control is active")
        try:
            if self.phase == "failed":
                raise ControlError(409, "Acceptance boundary failed and remains closed")
            if mode is None and self._cached and self._cached[0] == reset_id:
                if expected_generation == self._cached[1] and self.barrier.activity == self._cached[2] and self.barrier.open:
                    # A lost response is retryable, but never across an invisible
                    # controller process replacement in an unchanged container.
                    try:
                        state = controller.acceptance_state(timeout_seconds=self.settings.ACCEPTANCE_RESET_TIMEOUT_SECONDS)
                        if state.get("run_id") != self.settings.ACCEPTANCE_RUN_ID or state.get("generation") != self.barrier.generation or state.get("boot_id") != self._controller_boot or (self._ownership is not None and state.get("ownership") != self._ownership):
                            raise RuntimeError("Controller retry identity changed")
                    except Exception:
                        self.failure_phase = "verifying_retry"
                        self.phase = "failed"
                        self.baseline_verified = False
                        self.barrier.close()
                        raise ControlError(503, "Acceptance retry identity verification failed") from None
                    if self.barrier.activity != self._cached[2] or not self.barrier.open:
                        raise ControlError(409, "Stale reset retry after scenario admission")
                    return dict(self._cached[3])
                raise ControlError(409, "Stale reset retry after scenario admission")
            if mode is None and (reset_id in self._used_reset_ids or len(self._used_reset_ids) >= 10_000):
                raise ControlError(409, "Reset identifier is stale or run metadata capacity is exhausted")
            if expected_generation != self.barrier.generation:
                raise ControlError(409, "Acceptance generation conflict")
            if mode == "available" and (self._repository is None or self._token is None):
                raise ControlError(409, "Declared repository baseline is unavailable")
            deadline = monotonic() + self.settings.ACCEPTANCE_RESET_TIMEOUT_SECONDS
            done = threading.Event()
            outcome: list[dict[str, Any] | BaseException] = []

            def operation() -> None:
                try:
                    # Authenticate/schema/run checks already happened; Docker attestation precedes mutation.
                    with self._state_lock:
                        self._phase_timings = []
                        self._phase_started = None
                    self._phase("validating_ownership", deadline)
                    self._validate_ownership(controller, database, deadline)
                    self.baseline_verified = False
                    self._drain(deadline)
                    self._controller(controller, "quiesce", reset_id, expected_generation, deadline, **({"operation": "configuration"} if mode is not None else {}))
                    if mode is None:
                        self._phase("cleaning_previews", deadline)
                        self._controller(controller, "reset", reset_id, expected_generation, deadline)
                        self._phase("cleaning_files", deadline)
                        self.workspace.clean(deadline)
                        self.agent.clean(deadline)
                        self._phase("resetting_database", deadline)
                        snapshot = restore_database(database, self.settings, deadline)
                        self._phase("restoring_controls", deadline)
                        self._restore_controls()
                        self._phase("verifying", deadline)
                        verify_database(database, self.settings, snapshot)
                        self.workspace.verify()
                        self.agent.verify()
                        self._verify_controls()
                    else:
                        self._phase("configuring", deadline)
                        self.configuration = mode
                        if mode == "available" and self.repository() != (self._repository, self._token):
                            raise RuntimeError("Effective configuration mismatch")
                    self._validate_ownership(controller, database, deadline)
                    generation = expected_generation + (1 if mode is None else 0)
                    resumed = self._controller(controller, "resume", reset_id, expected_generation, deadline, generation=generation, baseline_verified=True)
                    if resumed.get("generation") != generation or resumed.get("phase") != "ready" or (mode is None and resumed.get("baseline_verified") is not True):
                        raise RuntimeError("Controller did not reopen the verified generation")
                    with self._state_lock, self.barrier._condition:
                        self._remaining(deadline)
                        self._baseline_activity = self.barrier.activity
                        self.barrier.reopen(generation)
                        self._finish_phase()
                        self.phase = "ready"
                        self.baseline_verified = mode is None
                        result = self.state()
                        if mode is None:
                            result["reset_id"] = reset_id
                            self._used_reset_ids.add(reset_id)
                            self._cached = (reset_id, expected_generation, self.barrier.activity, dict(result))
                        else:
                            self._cached = None
                        outcome.append(result)
                except BaseException as error:
                    with self._state_lock:
                        if self.phase != "failed":
                            self._finish_phase()
                            self.failure_phase = self.phase
                        self.phase = "failed"
                        self.baseline_verified = False
                        self.barrier.close()
                    outcome.append(error)
                finally:
                    done.set()

            self._operation = threading.Thread(target=operation, daemon=True)
            self._operation.start()
            if not done.wait(max(0, deadline - monotonic())):
                with self._state_lock:
                    self._finish_phase()
                    self.failure_phase = self.phase
                    self.phase = "failed"
                    self.baseline_verified = False
                    self.barrier.close()
                raise ControlError(504, f"Acceptance control deadline exceeded during {self.failure_phase}")
            self._operation.join()
            if not outcome or isinstance(outcome[0], BaseException):
                # Never serialize provider/controller/database exception text or credentials.
                raise ControlError(503, f"Acceptance control failed during {self.failure_phase or self.phase}")
            return outcome[0]
        finally:
            self._lock.release()


acceptance_reset = AcceptanceResetCoordinator()


def effective_repository() -> tuple[Any, Any]:
    if reset_enabled():
        return acceptance_reset.repository()
    return settings.DEMO_GITHUB_REPO, settings.DEMO_GITHUB_TOKEN
