# Full Stack FastAPI Template

A full-stack app template with a FastAPI backend and React frontend, providing user management (including admin/superuser roles) and a sample Items resource.

## Language

**Superuser**:
A User with `is_superuser=True`. Can manage other Users (create, edit, delete) via the admin page. Cannot delete their own account.
_Avoid_: Admin, root user

**Current user**:
The authenticated User making the request. Never selectable as a delete target for themselves, whether via single delete or bulk delete.
_Avoid_: Logged-in user, self

**Bulk delete (Users)**:
A single atomic operation that deletes a set of selected Users, and cascades to delete their Items, in one backend request. All-or-nothing: if any target User in the set is invalid (e.g. already deleted, or is the current user), the entire operation fails and no Users are deleted.
_Avoid_: Batch delete, mass delete
