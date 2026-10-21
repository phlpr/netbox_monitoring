(() => {
  const groups = {
    disk: ["metric", "warning", "critical", "exclude_paths"],
    cpu: ["metric", "warning", "critical", "window_seconds"],
    memory: ["metric", "warning", "critical", "window_seconds"],
    dns: ["record_type", "resolver", "expected_answers", "timeout_seconds", "measurement_location"],
    process: ["matcher", "min_count", "max_count"]
  };
  const defaults = {
    disk: { metric: "used_percent", warning: 80, critical: 90 },
    cpu: { metric: "utilization_percent", warning: 80, critical: 95, window_seconds: 300 },
    memory: { metric: "available_percent", warning: 20, critical: 10, window_seconds: 300 }
  };
  const metrics = {
    disk: ["used_percent", "free_percent", "free_gib"],
    cpu: ["utilization_percent", "load_1", "load_5", "load_15"],
    memory: ["available_percent", "available_gib"]
  };
  const valueOf = value => value && typeof value === "object" ? value.value : value;
  function init(form) {
    const type = form.querySelector("[data-monitoring-type]");
    if (!type || type.dataset.monitoringReady) return;
    type.dataset.monitoringReady = "true";
    form._monitoringController?.abort();
    const controller = new AbortController();
    form._monitoringController = controller;
    const prefix = type.name.slice(0, -"check_type".length);
    const field = name => form.querySelector('[name="' + prefix + name + '"]');
    const operation = form.querySelector("[data-monitoring-operation]");
    const rule = form.querySelector("[data-monitoring-rule]");
    const show = (name, visible) => {
      const input = field(name);
      if (!input) return;
      const row = input.closest(".row") || input.closest(".mb-3");
      if (row) row.hidden = !visible;
      input.disabled = !visible;
    };
    function update() {
      const op = operation ? operation.value : "add";
      const kind = op === "add" ? type.value : (field("parameter_kind")?.value || "disk");
      const visible = op === "disable" ? [] : (groups[kind] || []);
      for (const name of new Set(Object.values(groups).flat())) show(name, visible.includes(name));
      show("check_type", op === "add");
      show("target", op === "add" && !["cpu", "memory"].includes(kind));
      if (operation) show("rule", op !== "add");
      const metric = field("metric");
      if (metric && metrics[kind]) {
        for (const option of metric.options) option.disabled = !!option.value && !metrics[kind].includes(option.value);
        if (!metrics[kind].includes(metric.value)) metric.value = defaults[kind].metric;
      }
      const key = field("key");
      if (key) key.readOnly = op !== "add";
    }
    type.addEventListener("change", () => {
      for (const [name, value] of Object.entries(defaults[type.value] || {})) {
        const input = field(name); if (input) input.value = value;
      }
      if (["cpu", "memory"].includes(type.value) && field("target")) field("target").value = "";
      update();
    }, { signal: controller.signal });
    operation?.addEventListener("change", update, { signal: controller.signal });
    let generation = 0;
    let ruleReady = true;
    form.addEventListener("submit", event => {
      if (operation?.value === "change" && !ruleReady) event.preventDefault();
    }, { signal: controller.signal });
    rule?.addEventListener("change", async () => {
      const current = ++generation;
      ruleReady = false;
      if (!rule.value || !rule.dataset.monitoringRulesUrl) return;
      try {
        const response = await fetch(rule.dataset.monitoringRulesUrl + rule.value + "/", {
          headers: { Accept: "application/json" }, credentials: "same-origin", signal: controller.signal
        });
        if (!response.ok) throw new Error("The selected check could not be loaded.");
        const data = await response.json();
        if (current !== generation) return;
        const kind = valueOf(data.check_type);
        field("parameter_kind").value = kind;
        field("key").value = data.key;
        for (const name of new Set(Object.values(groups).flat())) {
          const input = field(name);
          if (input) input.value = "";
        }
        for (const [name, value] of Object.entries(data.parameters)) {
          const input = field(name);
          if (input) input.value = Array.isArray(value) ? value.join("\n") : (value ?? "");
        }
        ruleReady = true;
        form.querySelector("[data-monitoring-rule-error]")?.remove();
        update();
      } catch (error) {
        if (controller.signal.aborted) return;
        // A visible validation error explains failure without submitting stale values.
        let alert = form.querySelector("[data-monitoring-rule-error]");
        if (!alert) {
          alert = document.createElement("div");
          alert.className = "alert alert-danger";
          alert.dataset.monitoringRuleError = "";
          form.prepend(alert);
        }
        alert.textContent = error.message;
      }
    }, { signal: controller.signal });
    update();
  }
  document.querySelectorAll("form").forEach(init);
  if (!window.netboxMonitoringForms) {
    window.netboxMonitoringForms = true;
    document.addEventListener("htmx:afterSwap", () => document.querySelectorAll("form").forEach(init));
  }
})();