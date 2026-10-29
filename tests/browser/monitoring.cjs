/* Native NetBox browser regression checks against an isolated fixture database.
 * Run with a private JSON fixture path in MONITORING_BROWSER_STATE.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('playwright');

(async () => {
  const fixture = JSON.parse(fs.readFileSync(process.env.MONITORING_BROWSER_STATE, 'utf8'));
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {})
  });
  try {
    const context = await browser.newContext();
    await context.addCookies([fixture.cookie]);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const go = async path => {
      const response = await page.goto(fixture.base_url + path);
      assert.equal(response.status(), 200);
    };
    const select = async (name, id, label) => {
      await page.locator(`[name="${name}"]`).evaluate((input, option) => {
        const ts = input.tomselect;
        ts.addOption({ [ts.settings.valueField || "id"]: String(option.id), [ts.settings.labelField || "display"]: option.label });
        ts.setValue(String(option.id));
      }, { id, label });
    };
    await go('/plugins/monitoring/monitoring-profiles/add/');
    assert.equal(await page.locator('[name="status"]').inputValue(), 'active');
    assert.equal(await page.locator('[name="object_types"]').count(), 1);
    const objectTypeIds = await page.locator('[name="object_types"] option').evaluateAll(
      options => options.map(option => Number(option.value)));
    assert.ok(objectTypeIds.includes(fixture.site_object_type_id));
    assert.ok(objectTypeIds.includes(fixture.ipaddress_object_type_id));
    assert.equal(await page.getByRole('heading', { name: 'Ownership', exact: true }).count(), 1);
    const order = await page.locator('select[name="owner_group"], select[name="owner"]').evaluateAll(
      fields => fields.map(field => field.name));
    assert.deepEqual(order, ['owner_group', 'owner']);

    await go('/plugins/monitoring/monitoring-check-rules/add/');
    assert.equal(await page.locator('[name="check_type"]').count(), 0);
    await select('key', fixture.cpu_key_id, fixture.cpu_key_name);
    await page.waitForFunction(() => document.querySelector('[name="parameter_kind"]').value === 'cpu');
    assert.equal(await page.locator('[name="window_seconds"]').isEnabled(), true);
    assert.equal(await page.locator('[name="warning"]').inputValue(), '80');
    assert.equal(await page.locator('[name="target"]').isEnabled(), false);
    await select('key', fixture.disk_key_id, fixture.disk_key_name);
    await page.waitForFunction(() => document.querySelector('[name="parameter_kind"]').value === 'disk');
    assert.equal(await page.locator('[name="exclude_paths"]').isEnabled(), true);
    assert.equal(await page.locator('[name="target"]').inputValue(), '*');

    await go(`/virtualization/virtual-machines/${fixture.vm_id}/monitoring/`);
    await page.getByRole('link', { name: 'Add asset Exception', exact: true }).click();
    assert.equal(await page.locator('[name="assigned_object_id"]').inputValue(), String(fixture.vm_id));
    assert.equal(await page.locator('[name="assigned_object_type"]').isVisible(), false);
    assert.equal(await page.locator('[name="assigned_object_id"]').isVisible(), false);
    assert.equal(await page.getByLabel(/assigned object (type|id)/i).count(), 0);
    assert.equal(await page.locator('[name="profile"]').count(), 0);
    assert.equal(await page.locator('[name="rule"]').count(), 0);
    const baseLoaded = page.waitForResponse(response => response.url().includes('/base-config/') && response.ok());
    await select('key', fixture.disk_key_id, fixture.disk_key_name);
    await baseLoaded;
    await page.waitForFunction(() => document.querySelector('[name="parameter_kind"]').value === 'disk');
    assert.equal(await page.locator('[name="key"]').inputValue(), String(fixture.disk_key_id));
    assert.equal(await page.locator('[name="warning"]').inputValue(), '80');
    assert.equal(await page.locator('[name="critical"]').inputValue(), '90');
    assert.equal(await page.locator('[name="key"]').isEnabled(), true);
    await go(`/dcim/sites/${fixture.site_id}/monitoring/`);
    await page.getByRole('link', { name: 'Add asset Exception', exact: true }).click();
    assert.equal(await page.locator('[name="assigned_object_id"]').inputValue(), String(fixture.site_id));
    assert.equal(await page.locator('[name="assigned_object_type"]').inputValue(), String(fixture.site_object_type_id));
    await go(`/virtualization/virtual-machines/${fixture.vm_id}/`);
    assert.equal(await page.locator('[data-monitoring-assignments]').count(), 1);
    await page.getByRole('link', { name: 'Assign profile', exact: true }).click();
    assert.equal(await page.locator('[name="assigned_object_id"]').inputValue(), String(fixture.vm_id));
    assert.equal(await page.locator('[name="assigned_object_type"]').isVisible(), false);
    assert.equal(await page.locator('[name="assigned_object_id"]').isVisible(), false);
    assert.equal(await page.getByLabel(/assigned object (type|id)/i).count(), 0);
    assert.equal(await page.locator('[name="weight"]').inputValue(), '100');
    await select('profile', fixture.extra_profile_id, fixture.extra_profile_name);
    await page.locator('[name="weight"]').fill('200');
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await page.waitForURL(`**/virtualization/virtual-machines/${fixture.vm_id}/`);
    assert.equal(await page.locator('[data-monitoring-assignments] tbody tr').count(), 2);
    const config = await context.request.get(fixture.base_url + `/api/plugins/monitoring/assets/virtualization.virtualmachine/${fixture.vm_id}/config/`);
    const data = await config.json();
    assert.equal(data.schema_version, 2);
    assert.deepEqual(data.profiles.map(profile => profile.weight), [200, 100]);
    assert.equal(data.checks[0].target, '/var');
    assert.equal(data.checks[0].parameters.warning, 70);
    assert.deepEqual(errors, []);
    console.log('Browser checks passed: profile status/object types/ownership, key-driven parameter fields, asset exception baseline, assignment card and weighted configuration.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
