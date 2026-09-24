import { expect, test } from "@playwright/test"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { createUser } from "./utils/privateApi"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser } from "./utils/user"

test("Admin page is accessible and shows correct title", async ({ page }) => {
  await page.goto("/admin")
  await expect(page.getByRole("heading", { name: "Users" })).toBeVisible()
  await expect(
    page.getByText("Manage user accounts and permissions"),
  ).toBeVisible()
})

test("Add User button is visible", async ({ page }) => {
  await page.goto("/admin")
  await expect(page.getByRole("button", { name: "Add User" })).toBeVisible()
})

test.describe("Admin bulk user deletion", () => {
  test("selects eligible users but not the current user", async ({ page }) => {
    const firstUser = await createUser({
      email: randomEmail(),
      password: randomPassword(),
    })
    const secondUser = await createUser({
      email: randomEmail(),
      password: randomPassword(),
    })

    await page.goto("/admin")

    const deleteButton = page.getByRole("button", { name: "Delete User(s)" })
    await expect(deleteButton).toBeDisabled()
    await page.getByLabel(`Select ${firstUser.email}`).check()
    await page.getByLabel(`Select ${secondUser.email}`).check()

    await expect(page.getByLabel(`Select ${firstUser.email}`)).toBeChecked()
    await expect(page.getByLabel(`Select ${secondUser.email}`)).toBeChecked()
    await expect(page.getByLabel(`Select ${firstSuperuser}`)).toBeDisabled()
    await expect(deleteButton).toBeEnabled()
  })

  test("select all is limited to the visible page and becomes indeterminate", async ({
    page,
  }) => {
    await Promise.all(
      Array.from({ length: 10 }, () =>
        createUser({ email: randomEmail(), password: randomPassword() }),
      ),
    )

    await page.goto("/admin")
    await page.getByRole("combobox").click()
    await page.getByRole("option", { name: "5", exact: true }).click()

    const selectPage = page.getByLabel("Select all users on current page")
    await selectPage.check()
    const rowCheckboxes = page.getByRole("checkbox", {
      name: /^Select (?!all users)/,
    })
    await expect(rowCheckboxes).toHaveCount(5)
    for (let index = 0; index < 5; index += 1) {
      await expect(rowCheckboxes.nth(index)).toBeChecked()
    }

    await page.getByRole("button", { name: "Go to next page" }).click()
    for (const checkbox of await rowCheckboxes.all()) {
      await expect(checkbox).not.toBeChecked()
    }

    await page.getByRole("button", { name: "Go to previous page" }).click()
    await rowCheckboxes.first().uncheck()
    await expect(selectPage).toHaveAttribute("data-state", "indeterminate")
  })

  test("confirmation describes count and permanent Item deletion", async ({
    page,
  }) => {
    const users = await Promise.all(
      Array.from({ length: 3 }, () =>
        createUser({ email: randomEmail(), password: randomPassword() }),
      ),
    )
    await page.goto("/admin")
    for (const user of users)
      await page.getByLabel(`Select ${user.email}`).check()

    await page.getByRole("button", { name: "Delete User(s)" }).click()

    const dialog = page.getByRole("dialog")
    await expect(dialog).toContainText("3 users")
    await expect(dialog).toContainText("Items")
    await expect(dialog).toContainText("permanently deleted")
  })

  test("prevents duplicate submission while pending", async ({ page }) => {
    const user = await createUser({
      email: randomEmail(),
      password: randomPassword(),
    })
    let releaseRequest: (() => void) | undefined
    await page.route("**/api/v1/users/bulk-delete", async (route) => {
      await new Promise<void>((resolve) => {
        releaseRequest = resolve
      })
      await route.fulfill({ status: 200, json: { message: "ok" } })
    })
    await page.goto("/admin")
    await page.getByLabel(`Select ${user.email}`).check()
    await page.getByRole("button", { name: "Delete User(s)" }).click()

    const confirmButton = page.getByRole("button", { name: "Delete users" })
    await confirmButton.click()
    await expect(confirmButton).toBeDisabled()
    await expect(confirmButton.locator("svg.animate-spin")).toBeVisible()

    releaseRequest?.()
    await expect(page.getByRole("dialog")).not.toBeVisible()
  })

  test("reports success, removes rows, and clears selection", async ({
    page,
  }) => {
    const user = await createUser({
      email: randomEmail(),
      password: randomPassword(),
    })
    await page.goto("/admin")
    await page.getByLabel(`Select ${user.email}`).check()
    await page.getByRole("button", { name: "Delete User(s)" }).click()
    await page.getByRole("button", { name: "Delete users" }).click()

    await expect(page.getByText("Users deleted successfully")).toBeVisible()
    await expect(page.getByRole("dialog")).not.toBeVisible()
    await expect(
      page.getByRole("row").filter({ hasText: user.email }),
    ).not.toBeVisible()
    await expect(
      page.getByRole("button", { name: "Delete User(s)" }),
    ).toBeDisabled()
  })

  test("reports rejection and closes the dialog", async ({ page }) => {
    const user = await createUser({
      email: randomEmail(),
      password: randomPassword(),
    })
    await page.route("**/api/v1/users/bulk-delete", (route) =>
      route.fulfill({ status: 404, json: { detail: "User not found" } }),
    )
    await page.goto("/admin")
    await page.getByLabel(`Select ${user.email}`).check()
    await page.getByRole("button", { name: "Delete User(s)" }).click()
    await page.getByRole("button", { name: "Delete users" }).click()

    await expect(page.getByText("Something went wrong!")).toBeVisible()
    await expect(page.getByText("User not found")).toBeVisible()
    await expect(page.getByRole("dialog")).not.toBeVisible()
  })
})

test.describe("Admin user management", () => {
  test("Create a new user successfully", async ({ page }) => {
    await page.goto("/admin")

    const email = randomEmail()
    const password = randomPassword()
    const fullName = "Test User Admin"

    await page.getByRole("button", { name: "Add User" }).click()

    await page.getByPlaceholder("Email").fill(email)
    await page.getByPlaceholder("Full name").fill(fullName)
    await page.getByPlaceholder("Password").first().fill(password)
    await page.getByPlaceholder("Password").last().fill(password)

    await page.getByRole("button", { name: "Save" }).click()

    await expect(page.getByText("User created successfully")).toBeVisible()

    await expect(page.getByRole("dialog")).not.toBeVisible()

    const userRow = page.getByRole("row").filter({ hasText: email })
    await expect(userRow).toBeVisible()
  })

  test("Create a superuser", async ({ page }) => {
    await page.goto("/admin")

    const email = randomEmail()
    const password = randomPassword()

    await page.getByRole("button", { name: "Add User" }).click()

    await page.getByPlaceholder("Email").fill(email)
    await page.getByPlaceholder("Password").first().fill(password)
    await page.getByPlaceholder("Password").last().fill(password)
    await page.getByLabel("Is superuser?").check()
    await page.getByLabel("Is active?").check()

    await page.getByRole("button", { name: "Save" }).click()

    await expect(page.getByText("User created successfully")).toBeVisible()

    await expect(page.getByRole("dialog")).not.toBeVisible()

    const userRow = page.getByRole("row").filter({ hasText: email })
    await expect(userRow.getByText("Superuser")).toBeVisible()
  })

  test("Edit a user successfully", async ({ page }) => {
    await page.goto("/admin")

    const email = randomEmail()
    const password = randomPassword()
    const originalName = "Original Name"
    const updatedName = "Updated Name"

    await page.getByRole("button", { name: "Add User" }).click()
    await page.getByPlaceholder("Email").fill(email)
    await page.getByPlaceholder("Full name").fill(originalName)
    await page.getByPlaceholder("Password").first().fill(password)
    await page.getByPlaceholder("Password").last().fill(password)
    await page.getByRole("button", { name: "Save" }).click()

    await expect(page.getByText("User created successfully")).toBeVisible()
    await expect(page.getByRole("dialog")).not.toBeVisible()

    const userRow = page.getByRole("row").filter({ hasText: email })
    await userRow.getByRole("button").click()

    await page.getByRole("menuitem", { name: "Edit User" }).click()

    await page.getByPlaceholder("Full name").fill(updatedName)
    await page.getByRole("button", { name: "Save" }).click()

    await expect(page.getByText("User updated successfully")).toBeVisible()
    await expect(page.getByText(updatedName)).toBeVisible()
  })

  test("Delete a user successfully", async ({ page }) => {
    await page.goto("/admin")

    const email = randomEmail()
    const password = randomPassword()

    await page.getByRole("button", { name: "Add User" }).click()
    await page.getByPlaceholder("Email").fill(email)
    await page.getByPlaceholder("Password").first().fill(password)
    await page.getByPlaceholder("Password").last().fill(password)
    await page.getByRole("button", { name: "Save" }).click()

    await expect(page.getByText("User created successfully")).toBeVisible()

    await expect(page.getByRole("dialog")).not.toBeVisible()

    const userRow = page.getByRole("row").filter({ hasText: email })
    await userRow.getByRole("button").click()

    await page.getByRole("menuitem", { name: "Delete User" }).click()

    await page.getByRole("button", { name: "Delete" }).click()

    await expect(
      page.getByText("The user was deleted successfully"),
    ).toBeVisible()

    await expect(
      page.getByRole("row").filter({ hasText: email }),
    ).not.toBeVisible()
  })

  test("Cancel user creation", async ({ page }) => {
    await page.goto("/admin")

    await page.getByRole("button", { name: "Add User" }).click()
    await page.getByPlaceholder("Email").fill("test@example.com")

    await page.getByRole("button", { name: "Cancel" }).click()

    await expect(page.getByRole("dialog")).not.toBeVisible()
  })

  test("Email is required and must be valid", async ({ page }) => {
    await page.goto("/admin")

    await page.getByRole("button", { name: "Add User" }).click()

    await page.getByPlaceholder("Email").fill("invalid-email")
    await page.getByPlaceholder("Email").blur()

    await expect(page.getByText("Invalid email address")).toBeVisible()
  })

  test("Password must be at least 8 characters", async ({ page }) => {
    await page.goto("/admin")

    await page.getByRole("button", { name: "Add User" }).click()

    await page.getByPlaceholder("Email").fill(randomEmail())
    await page.getByPlaceholder("Password").first().fill("short")
    await page.getByPlaceholder("Password").last().fill("short")
    await page.getByRole("button", { name: "Save" }).click()

    await expect(
      page.getByText("Password must be at least 8 characters"),
    ).toBeVisible()
  })

  test("Passwords must match", async ({ page }) => {
    await page.goto("/admin")

    await page.getByRole("button", { name: "Add User" }).click()

    await page.getByPlaceholder("Email").fill(randomEmail())
    await page.getByPlaceholder("Password").first().fill(randomPassword())
    await page.getByPlaceholder("Password").last().fill("different12345")
    await page.getByPlaceholder("Password").last().blur()

    await expect(page.getByText("The passwords don't match")).toBeVisible()
  })
})

test.describe("Admin page access control", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("Non-superuser cannot access admin page", async ({ page }) => {
    const email = randomEmail()
    const password = randomPassword()

    await createUser({ email, password })
    await logInUser(page, email, password)

    await page.goto("/admin")

    await expect(page.getByRole("heading", { name: "Users" })).not.toBeVisible()
    await expect(page).not.toHaveURL(/\/admin/)
  })

  test("Superuser can access admin page", async ({ page }) => {
    await logInUser(page, firstSuperuser, firstSuperuserPassword)

    await page.goto("/admin")

    await expect(page.getByRole("heading", { name: "Users" })).toBeVisible()
  })
})
