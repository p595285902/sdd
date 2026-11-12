from pathlib import Path

import pytest

from app.services.preview_native_plan import (
    PreviewInstructionsError,
    config_command,
    read_startup_documents,
    resolve_native_plan,
)

WORKFLOW = """# Docker development
```sh
docker compose run --rm api python init.py
docker compose watch
```
Application: http://localhost:8765/
"""


def test_linked_workflow_is_ordered_source_backed_and_read_only(tmp_path: Path):
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'README.md').write_text(
        '# Development\n[Docker](docs/development.md#docker-development)\n'
        '## Alternative host-local development\n'
        '`python site/server.py` and `python api/server.py`\n'
    )
    (tmp_path / 'docs/development.md').write_text(WORKFLOW)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    plan = resolve_native_plan(tmp_path)
    assert plan is not None
    assert [command.argv for command in plan.commands] == [
        ['docker', 'compose', 'run', '--rm', 'api', 'python', 'init.py'],
        ['docker', 'compose', 'watch'],
    ]
    assert [command.kind for command in plan.commands] == ['setup', 'start']
    assert all(command.source['path'] == 'docs/development.md' for command in plan.commands)
    assert plan.application['port'] == 8765
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize(('entry', 'path'), [
    ('API Swagger UI is at http://localhost:8766/docs/.', '/docs/'),
    ('Application: http://localhost:8766/openapi.json.', '/openapi.json'),
    ('Application: http://localhost:8766/docs/v1.2/', '/docs/v1.2/'),
    ('Application: `http://localhost:8766/version.`.', '/version.'),
    ('Application: <http://localhost:8766/version.>.', '/version.'),
    ('Application: [Swagger](http://localhost:8766/docs/).', '/docs/'),
])
def test_documented_application_url_excludes_prose_punctuation(tmp_path: Path, entry: str, path: str):
    (tmp_path / 'README.md').write_text(WORKFLOW.replace('Application: http://localhost:8765/', entry))
    plan = resolve_native_plan(tmp_path)
    assert plan.application['port'] == 8766
    assert plan.application['path'] == path


def test_external_and_escaping_symlink_documents_are_not_read(tmp_path: Path):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    (tmp_path / 'secret.md').write_text(WORKFLOW)
    (checkout / 'outside.md').symlink_to(tmp_path / 'secret.md')
    (checkout / 'README.md').write_text('[External](https://example.com/start.md) [Escape](outside.md)')
    docs = read_startup_documents(checkout)
    assert [document.path for document in docs] == ['README.md']
    assert resolve_native_plan(checkout) is None


def test_cycles_and_duplicate_fragments_are_deduplicated(tmp_path: Path):
    (tmp_path / 'README.md').write_text('[One](start.md#one) [Two](start.md#two)')
    (tmp_path / 'start.md').write_text('[Back](README.md)\n' + WORKFLOW)
    plan = resolve_native_plan(tmp_path)
    assert len(plan.sources) == 2
    assert len(plan.commands) == 2


def test_traversal_depth_is_bounded(tmp_path: Path):
    for i, name in enumerate(['README.md', 'a.md', 'b.md', 'c.md', 'd.md', 'e.md']):
        names = ['README.md', 'a.md', 'b.md', 'c.md', 'd.md', 'e.md']
        (tmp_path / name).write_text(f'[Next]({names[i+1]})' if i < 5 else WORKFLOW)
    with pytest.raises(PreviewInstructionsError, match='budget'):
        read_startup_documents(tmp_path)


def test_document_size_budget(tmp_path: Path):
    (tmp_path / 'README.md').write_text('x' * (1024 * 1024 + 1))
    with pytest.raises(PreviewInstructionsError, match='text budget'):
        read_startup_documents(tmp_path)


def test_conflicting_full_stack_workflows_are_not_guessed(tmp_path: Path):
    (tmp_path / 'README.md').write_text(WORKFLOW + '\n## Another full stack\n`docker compose up -d`\n')
    with pytest.raises(PreviewInstructionsError, match='Conflicting.*README.md'):
        resolve_native_plan(tmp_path)


def test_maintenance_examples_are_not_startup(tmp_path: Path):
    (tmp_path / 'README.md').write_text(WORKFLOW + '\n## Testing\n`docker compose up test`\n## Cleanup\n`docker compose down --volumes`\n')
    plan = resolve_native_plan(tmp_path)
    assert len(plan.commands) == 2


def test_cd_and_and_sequencing_preserve_directory_and_global_options(tmp_path: Path):
    (tmp_path / 'app').mkdir()
    (tmp_path / 'README.md').write_text('''# Docker development
```sh
cd app && docker compose --env-file project.env -f stack.yml run --rm api init && docker compose --env-file project.env -f stack.yml watch
```
Application: http://localhost:8080/
''')
    plan = resolve_native_plan(tmp_path)
    assert all(command.cwd == 'app' for command in plan.commands)
    assert config_command(plan.commands[0].__dict__) == ['docker', 'compose', '--env-file', 'project.env', '-f', 'stack.yml', 'config', '--format', 'json']


def test_shell_failure_semantics_are_not_silently_changed(tmp_path: Path):
    (tmp_path / 'README.md').write_text('`docker compose run api init; docker compose watch`\nApplication: http://localhost:8765/')
    with pytest.raises(PreviewInstructionsError, match='unconditional shell sequencing'):
        resolve_native_plan(tmp_path)


def test_separate_native_blocks_preserve_directory_and_exported_environment(tmp_path: Path):
    (tmp_path / 'app').mkdir()
    (tmp_path / 'README.md').write_text('''# Docker development
```sh
cd app
export COMPOSE_PROFILES=development
cp example.env .env
docker compose run --rm api python init.py
```
```sh
docker compose watch
```
Application: http://localhost:8765/
''')
    plan = resolve_native_plan(tmp_path)
    assert [command.cwd for command in plan.commands] == ['app'] * 3
    assert plan.commands[0].argv == ['cp', 'example.env', '.env']
    assert all(command.env == {'COMPOSE_PROFILES': 'development'} for command in plan.commands)


@pytest.mark.parametrize('key', ['DOCKER_HOST', 'DOCKER_CONFIG', 'COMPOSE_FILE', 'COMPOSE_ENV_FILES', 'PATH'])
def test_documented_exports_cannot_redirect_runtime_controls(tmp_path: Path, key: str):
    (tmp_path / 'README.md').write_text(WORKFLOW.replace('docker compose run', f'export {key}=outside\ndocker compose run'))
    with pytest.raises(PreviewInstructionsError, match='runtime control'):
        resolve_native_plan(tmp_path)


def test_chat_local_clarification_selects_commands_without_modifying_checkout(tmp_path: Path):
    original = '# Development\nNo commands yet.\n'
    (tmp_path / 'README.md').write_text(original)
    plan = resolve_native_plan(tmp_path, answer='docker compose run --rm api python init.py\ndocker compose watch\nApplication: http://localhost:8765/')
    assert [command.kind for command in plan.commands] == ['setup', 'start']
    assert all(command.source['path'] == '<chat clarification>' for command in plan.commands)
    assert plan.application['port'] == 8765
    assert (tmp_path / 'README.md').read_text() == original


def test_discovery_does_not_read_environment_values(tmp_path: Path):
    (tmp_path / 'README.md').write_text(WORKFLOW)
    (tmp_path / '.env').symlink_to('/definitely-not-readable')
    assert resolve_native_plan(tmp_path) is not None
