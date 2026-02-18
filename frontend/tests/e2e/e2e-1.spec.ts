import { expect, test } from "@playwright/test";

test("E2E 1", async ({ page }) => {
  await page.addInitScript(() => {
    if (!window.sessionStorage.getItem("__e2e_cleared")) {
      window.localStorage.clear();
      window.sessionStorage.setItem("__e2e_cleared", "1");
    }
  });

  await page.goto("/");

  await page.getByTestId("analyze-button").click();

  const firstMistakeCard = page.getByTestId("mistake-card-0");
  await firstMistakeCard.waitFor({ state: "visible", timeout: 90_000 });
  await firstMistakeCard.click();

  await page.getByTestId("canvas-root").click();

  const noteCards = page.locator('[data-testid^="note-card-"]');
  await Promise.race([
    page.getByTestId("autosave-toast").waitFor({ state: "visible", timeout: 15_000 }),
    expect(noteCards.first()).toBeVisible({ timeout: 15_000 }),
  ]);

  await page.getByTestId("notebooks-toggle").click();
  await expect(page.getByTestId("notebooks-drawer")).toBeVisible();
  await page.getByTestId("notebook-item-inbox").click();
  await expect
    .poll(async () => noteCards.count(), { timeout: 15_000 })
    .toBeGreaterThan(0);

  await page.reload();
  await expect
    .poll(async () => page.locator('[data-testid^="note-card-"]').count(), { timeout: 15_000 })
    .toBeGreaterThan(0);
});
