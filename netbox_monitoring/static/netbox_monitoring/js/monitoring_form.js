(() => {
  const groups = {
    disk: ["metric", "warning", "critical", "exclude_paths"],
    cpu: ["metric", "warning", "critical", "window_seconds"],
    memory: ["metric", "warning", "critical", "window_seconds"],
    dns: ["record_type", "resolver", "expected_answers", "timeout_seconds", "measurement_location"],
    process: ["matcher", "min_count", "max_count"]
  };
  const metrics = {
    disk: ["used_percent", "free_percent", "free_gib"],
    cpu: ["utilization_percent", "load_1", "load_5", "load_15"],
    memory: ["available_percent", "available_gib"]
  };
  const parameters = [...new Set(Object.values(groups).flat())];
  const valueOf = value => value && typeof value === "object" ? value.value : value;
  function init(form) {
    const kind = form.querySelector("[data-monitoring-kind]");
    if (!kind || kind.dataset.monitoringReady) return;
    kind.dataset.monitoringReady = "true";
    form._monitoringController?.abort();
    const controller = new AbortController();
    form._monitoringController = controller;
    const prefix = kind.name.slice(0, -"parameter_kind".length);
    const field = name => form.querySelector('[name="' + prefix + name + '"]');
    const key = field("key");
    const rule = form.querySelector("[data-monitoring-rule]");
    const operation = form.querySelector("[data-monitoring-operation]");
    const currentOperation = () => operation?.value || "add";
    let generation = 0;
    let ready = true;
    const show = (name, visible) => {
      const input = field(name);
      if (!input) return;
      const row = input.closest(".row") || input.closest(".mb-3");
      if (row) row.hidden = !visible;
      input.disabled = !visible;
    };
    function update() {
      const op = currentOperation();
      const visible = op === "disable" ? [] : (groups[kind.value] || []);
      for (const name of parameters) show(name, visible.includes(name));
      show("target", op === "add" && !!kind.value && !["cpu", "memory"].includes(kind.value));
      show("key", op === "add");
      if (operation) show("rule", op !== "add");
      const metric = field("metric");
      if (metric && metrics[kind.value]) {
        for (const option of metric.options) {
          option.disabled = !!option.value && !metrics[kind.value].includes(option.value);
        }
      }
    }
    function selectKey(data) {
      if (key.tomselect) {
        key.tomselect.addOption({ value: String(data.id), text: data.name || data.display });
        key.tomselect.setValue(String(data.id), true);
      } else {
        if (![...key.options].some(option => option.value === String(data.id))) {
          key.add(new Option(data.name || data.display, String(data.id)));
        }
        key.value = String(data.id);
      }
    }
    function showError(message) {
      let alert = form.querySelector("[data-monitoring-load-error]");
      if (!alert) {
        alert = document.createElement("div");
        alert.className = "alert alert-danger";
        alert.dataset.monitoringLoadError = "";
        form.prepend(alert);
      }
      alert.textContent = message;
    }
    async function load(fromRule) {
      const current = ++generation;
      const select = fromRule ? rule : key;
      const base = fromRule ? rule?.dataset.monitoringRulesUrl : key.dataset.monitoringKeysUrl;
      ready = false;
      if (!select?.value || !base) {
        kind.value = "";
        update();
        return;
      }
      try {
        const response = await fetch(base + select.value + "/", {
          headers: { Accept: "application/json" }, credentials: "same-origin", signal: controller.signal
        });
        if (!response.ok) throw new Error("The selected monitoring check could not be loaded.");
        const data = await response.json();
        if (current !== generation) return;
        kind.value = valueOf(data.check_type);
        if (fromRule) selectKey(data.key);
        for (const name of parameters) {
          const input = field(name);
          if (input) input.value = "";
        }
        for (const [name, value] of Object.entries(fromRule ? data.parameters : data.default_parameters)) {
          const input = field(name);
          if (input) input.value = Array.isArray(value) ? value.join("\n") : (value ?? "");
        }
        const target = field("target");
        if (target && ["cpu", "memory"].includes(kind.value)) target.value = "";
        if (target && kind.value === "disk" && !target.value) target.value = "*";
        ready = true;
        form.querySelector("[data-monitoring-load-error]")?.remove();
        update();
      } catch (error) {
        if (!controller.signal.aborted && current === generation) showError(error.message);
      }
    }
    key.addEventListener("change", () => {
      if (currentOperation() === "add") load(false);
    }, { signal: controller.signal });
    rule?.addEventListener("change", () => load(true), { signal: controller.signal });
    operation?.addEventListener("change", () => {
      update();
      load(currentOperation() !== "add");
    }, { signal: controller.signal });
    form.addEventListener("submit", event => {
      if (!ready && currentOperation() !== "disable") event.preventDefault();
    }, { signal: controller.signal });
    update();
  }
  document.querySelectorAll("form").forEach(init);
  if (!window.netboxMonitoringForms) {
    window.netboxMonitoringForms = true;
    document.addEventListener("htmx:afterSwap", () => document.querySelectorAll("form").forEach(init));
  }
})();
