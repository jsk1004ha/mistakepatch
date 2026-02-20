import { expect, test } from "@playwright/test";

test("E2E 2", async ({ page }) => {
  const notebookName = "Math Notes";
  const notebooksDrawer = page.getByTestId("notebooks-drawer");
  const drawerBackdrop = page.locator(".drawerBackdrop");

  const ensureNotebooksDrawerOpen = async () => {
    if (!(await notebooksDrawer.isVisible())) {
      await page.getByTestId("notebooks-toggle").click();
    }
    await expect(notebooksDrawer).toBeVisible();
  };

  const closeNotebooksDrawerIfOpen = async () => {
    if (await notebooksDrawer.isVisible()) {
      await drawerBackdrop.click();
      await expect(notebooksDrawer).toBeHidden();
    }
  };

  await page.addInitScript(() => {
    if (!window.sessionStorage.getItem("__e2e_cleared")) {
      window.localStorage.clear();
      window.sessionStorage.setItem("__e2e_cleared", "1");
    }
  });

  await page.goto("/");

  await ensureNotebooksDrawerOpen();

  await page.getByTestId("drawer-new-notebook").click();
  const notebookInput = page.getByTestId("drawer-new-notebook-name");
  await notebookInput.fill(notebookName);
  await page.getByTestId("drawer-create-notebook").click();
  await expect(page.getByText(notebookName, { exact: true }).first()).toBeVisible();

  await closeNotebooksDrawerIfOpen();

  await page.getByTestId("analyze-button").click();

  const firstMistakeCard = page.getByTestId("mistake-card-0");
  await firstMistakeCard.waitFor({ state: "visible", timeout: 90_000 });
  await firstMistakeCard.click();
  await page.getByTestId("canvas-root").click();

  const firstNoteCard = page.locator('[data-testid^="note-card-"]').first();
  await expect(firstNoteCard).toBeVisible({ timeout: 15_000 });

  await firstNoteCard.click();
  await expect(page.getByTestId("note-detail")).toBeVisible();
  await page.getByTestId("note-move-select").selectOption({ label: notebookName });
  await page.getByTestId("note-delete").click();

  await ensureNotebooksDrawerOpen();
  await page.getByTestId("notebook-item-trash").click();
  const firstRestoreButton = page.locator('[data-testid^="trash-restore-"]').first();
  await expect(firstRestoreButton).toBeVisible({ timeout: 15_000 });
  await firstRestoreButton.click();
  await page.getByTestId("drawer-back").click();
  await expect(page.getByText(notebookName, { exact: true }).first()).toBeVisible();

  await ensureNotebooksDrawerOpen();
  await page.getByText(notebookName, { exact: true }).first().click();
  await closeNotebooksDrawerIfOpen();
  await expect
    .poll(async () => page.locator('[data-testid^="note-card-"]').count(), { timeout: 15_000 })
    .toBeGreaterThan(0);

  await page.locator('[data-testid^="note-card-"]').first().click();
  await expect(page.getByTestId("note-detail")).toBeVisible();
  await page.getByTestId("note-delete").click();

  await ensureNotebooksDrawerOpen();
  await page.getByTestId("notebook-item-trash").click();
  await page.getByTestId("trash-empty").click();
  await page.getByTestId("confirm-ok").click();

  await page.reload();
  await ensureNotebooksDrawerOpen();
  await page.getByTestId("notebook-item-trash").click();
  await expect
    .poll(async () => page.locator('[data-testid^="trash-restore-"]').count(), { timeout: 15_000 })
    .toBe(0);
});
