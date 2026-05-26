const TW_APP = window.TW_APP || (window.TW_APP = {
    charts: [],
    navigationReady: false,
    routeController: null,
    scrollCleanup: null,
    scrollPositions: {},
    currentUrl: window.location.href
});

function baseChartOption(title) {
    return {
        backgroundColor: "transparent",
        title: {
            text: title || "",
            left: "center",
            textStyle: {
                fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Display', sans-serif",
                fontSize: 16,
                fontWeight: 700,
                color: "#111317"
            }
        },
        tooltip: {
            trigger: "axis",
            backgroundColor: "rgba(17,19,23,0.92)",
            borderWidth: 0,
            textStyle: { color: "#fff" }
        },
        grid: { left: 48, right: 24, top: 58, bottom: 48 }
    };
}

function safeInitChart(elementId) {
    const node = document.getElementById(elementId);
    if (!node || typeof echarts === "undefined") {
        return null;
    }
    const chart = echarts.init(node);
    TW_APP.charts.push(chart);
    return chart;
}

function disposeRenderedCharts() {
    TW_APP.charts.forEach((chart) => {
        if (chart && typeof chart.dispose === "function" && !chart.isDisposed()) {
            chart.dispose();
        }
    });
    TW_APP.charts = [];
}

window.renderBarChart = function renderBarChart(elementId, payload) {
    const chart = safeInitChart(elementId);
    if (!chart) return;
    const option = baseChartOption(payload.title);
    option.xAxis = { type: "category", data: payload.labels, axisLabel: { color: "#656d78", rotate: 20 }, axisLine: { lineStyle: { color: "rgba(17,19,23,0.12)" } } };
    option.yAxis = { type: "value", axisLabel: { color: "#656d78" }, splitLine: { lineStyle: { color: "rgba(17,19,23,0.07)" } } };
    option.series = [{
        type: "bar",
        data: payload.values,
        barWidth: 28,
        itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: "#0b6cff" },
                { offset: 1, color: "#19a974" }
            ]),
            borderRadius: [14, 14, 0, 0]
        }
    }];
    chart.setOption(option);
    window.addEventListener("resize", () => chart.resize());
};

window.renderGroupedBarChart = function renderGroupedBarChart(elementId, payload) {
    const chart = safeInitChart(elementId);
    if (!chart) return;
    const option = baseChartOption(payload.title);
    option.legend = { top: 30 };
    option.xAxis = { type: "category", data: payload.labels, axisLabel: { color: "#656d78" }, axisLine: { lineStyle: { color: "rgba(17,19,23,0.12)" } } };
    option.yAxis = { type: "value", axisLabel: { color: "#656d78" }, splitLine: { lineStyle: { color: "rgba(17,19,23,0.07)" } } };
    option.series = payload.series.map((item, index) => ({
        name: item.name,
        type: "bar",
        data: item.values,
        itemStyle: {
            color: index === 0 ? "#0b6cff" : "#19a974",
            borderRadius: [8, 8, 0, 0]
        }
    }));
    chart.setOption(option);
    window.addEventListener("resize", () => chart.resize());
};

window.renderLineChart = function renderLineChart(elementId, payload) {
    const chart = safeInitChart(elementId);
    if (!chart) return;
    const option = baseChartOption(payload.title);
    option.legend = { top: 30 };
    option.xAxis = { type: "category", data: payload.labels, axisLabel: { color: "#656d78" }, axisLine: { lineStyle: { color: "rgba(17,19,23,0.12)" } } };
    option.yAxis = { type: "value", axisLabel: { color: "#656d78" }, splitLine: { lineStyle: { color: "rgba(17,19,23,0.07)" } } };
    option.series = payload.series.map((item, index) => ({
        name: item.name,
        type: "line",
        smooth: true,
        data: item.values,
        symbolSize: 8,
        lineStyle: { width: 3 },
        itemStyle: { color: index === 0 ? "#0b6cff" : index === 1 ? "#19a974" : "#ff9f1c" },
        areaStyle: index === 0 ? { color: "rgba(11,108,255,0.08)" } : undefined
    }));
    if (payload.visibleWindow && payload.labels.length > payload.visibleWindow) {
        const startValue = payload.labels.length - payload.visibleWindow;
        option.grid.bottom = 72;
        option.dataZoom = [
            {
                type: "slider",
                startValue,
                endValue: payload.labels.length - 1,
                height: 18,
                bottom: 18,
                borderColor: "rgba(11,108,255,0.18)",
                fillerColor: "rgba(11,108,255,0.12)",
                handleStyle: { color: "#0b6cff" },
                textStyle: { color: "#656d78" }
            },
            {
                type: "inside",
                startValue,
                endValue: payload.labels.length - 1,
                zoomOnMouseWheel: true,
                moveOnMouseMove: true
            }
        ];
    }
    chart.setOption(option);
    window.addEventListener("resize", () => chart.resize());
};

function appendAiMessage(container, role, text) {
    const node = document.createElement("div");
    node.className = `ai-message ${role}`;
    node.textContent = text;
    container.appendChild(node);
    container.scrollTop = container.scrollHeight;
}

function initAssistant() {
    const panel = document.querySelector("[data-ai-panel]");
    const toggles = document.querySelectorAll("[data-ai-toggle]");
    const form = document.querySelector("[data-ai-form]");
    const messages = document.querySelector("[data-ai-messages]");
    if (!panel || !form || !messages) return;
    if (panel.dataset.aiReady === "1") return;
    panel.dataset.aiReady = "1";

    toggles.forEach((toggle) => {
        toggle.addEventListener("click", () => {
            panel.classList.toggle("open");
        });
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const input = form.elements.message;
        const text = input.value.trim();
        if (!text) return;
        appendAiMessage(messages, "user", text);
        input.value = "";
        appendAiMessage(messages, "assistant", "正在查询本地推荐数据...");
        const pending = messages.lastElementChild;
        try {
            const response = await fetch("/api/assistant", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: text })
            });
            const payload = await response.json();
            pending.textContent = payload.answer || "没有生成有效回答。";
        } catch (error) {
            pending.textContent = "助手接口暂时不可用，请稍后再试。";
        }
    });

    const params = new URLSearchParams(window.location.search);
    if (params.get("assistant") === "open") {
        panel.classList.add("open");
        const demoQuestion = params.get("ask");
        if (demoQuestion) {
            form.elements.message.value = demoQuestion;
            form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
        }
    }
}

function initCitySuggestions() {
    const form = document.querySelector("[data-city-suggest-form]");
    if (!form) return;

    const input = form.querySelector("[data-city-suggest-input]");
    const list = form.querySelector("[data-city-suggest-list]");
    const searchUrl = form.dataset.citySearchUrl;
    if (!input || !list || !searchUrl) return;

    const cache = new Map();
    let debounceTimer = null;
    let controller = null;

    function clearCandidates(params) {
        [
            "candidate_slug",
            "candidate_name",
            "candidate_latitude",
            "candidate_longitude",
            "candidate_province",
            "candidate_country",
            "candidate_display_name"
        ].forEach((key) => params.delete(key));
    }

    function selectCity(city) {
        const target = new URL(`/city/${encodeURIComponent(city.slug || "")}`, window.location.origin);
        const params = new URLSearchParams(window.location.search);
        clearCandidates(params);
        params.set("autoload", "1");
        params.set("name", city.name || "");
        params.set("latitude", city.latitude || "");
        params.set("longitude", city.longitude || "");
        params.set("province", city.province || "");
        params.set("country", city.country || "");
        target.search = params.toString();
        if (window.navigateWithinApp) {
            window.navigateWithinApp(target.toString());
            return;
        }
        window.location.href = target.toString();
    }

    function renderSuggestions(results) {
        list.innerHTML = "";
        if (!results.length) {
            list.hidden = true;
            return;
        }
        results.forEach((city) => {
            const button = document.createElement("button");
            button.type = "button";
            const name = document.createElement("span");
            name.className = "city-suggest-name";
            name.textContent = city.name || "";
            const detail = document.createElement("small");
            detail.textContent = city.display_name || "";
            button.appendChild(name);
            if (detail.textContent) button.appendChild(detail);
            button.addEventListener("mousedown", (event) => {
                event.preventDefault();
                selectCity(city);
            });
            list.appendChild(button);
        });
        list.hidden = false;
    }

    async function fetchSuggestions(query) {
        if (cache.has(query)) {
            renderSuggestions(cache.get(query));
            return;
        }
        if (controller) controller.abort();
        controller = new AbortController();
        const params = new URLSearchParams({ q: query, local_only: "1" });
        try {
            const response = await fetch(`${searchUrl}?${params}`, { signal: controller.signal });
            const payload = await response.json();
            const results = Array.isArray(payload.results) ? payload.results : [];
            cache.set(query, results);
            renderSuggestions(results);
        } catch (error) {
            if (error.name !== "AbortError") {
                list.hidden = true;
            }
        }
    }

    input.addEventListener("input", () => {
        const query = input.value.trim();
        window.clearTimeout(debounceTimer);
        if (!query) {
            list.hidden = true;
            return;
        }
        debounceTimer = window.setTimeout(() => fetchSuggestions(query), 120);
    });

    input.addEventListener("focus", () => {
        const query = input.value.trim();
        if (query && cache.has(query)) {
            renderSuggestions(cache.get(query));
        }
    });

    input.addEventListener("blur", () => {
        window.setTimeout(() => {
            list.hidden = true;
        }, 120);
    });

    form.addEventListener("submit", () => {
        list.hidden = true;
    });
}

function initRefreshProgress() {
    const form = document.querySelector(".refresh-form");
    const modal = document.querySelector("[data-refresh-modal]");
    if (!form || !modal || typeof EventSource === "undefined") return;
    if (form.dataset.refreshProgressReady === "1") return;
    form.dataset.refreshProgressReady = "1";

    const percentNode = modal.querySelector("[data-refresh-percent]");
    const barNode = modal.querySelector("[data-refresh-bar]");
    const stepsNode = modal.querySelector("[data-refresh-steps]");
    const messageNode = modal.querySelector("[data-refresh-message]");
    const nextNode = modal.querySelector("[data-refresh-next]");
    const closeNode = modal.querySelector("[data-refresh-close]");
    let redirectUrl = null;
    let eventSource = null;

    function openModal() {
        modal.classList.add("open");
        redirectUrl = null;
        if (percentNode) percentNode.textContent = "0%";
        if (barNode) barNode.style.width = "0%";
        if (stepsNode) stepsNode.innerHTML = '<li class="active">正在创建刷新任务</li>';
        if (messageNode) messageNode.textContent = "正在连接后端刷新任务。";
        if (nextNode) nextNode.textContent = "下一步：等待服务端返回任务编号。";
    }

    function appendStep(text, state) {
        if (!stepsNode || !text) return;
        const current = stepsNode.querySelector("li.active");
        if (current) {
            current.classList.remove("active");
            current.classList.add("done");
        }
        const item = document.createElement("li");
        item.className = state || "active";
        item.textContent = text;
        stepsNode.appendChild(item);
        stepsNode.scrollTop = stepsNode.scrollHeight;
    }

    function applyProgress(event) {
        const step = Number(event.step || 0);
        const total = Number(event.total || 1);
        const percent = Math.max(0, Math.min(100, Math.round((step / total) * 100)));
        if (percentNode) percentNode.textContent = `${percent}%`;
        if (barNode) barNode.style.width = `${percent}%`;
        if (messageNode) messageNode.textContent = event.message || "";
        if (nextNode) nextNode.textContent = event.next_step || "";
        if (event.stage && event.status !== "heartbeat") {
            appendStep(`${event.stage}：${event.message || ""}`, event.status === "done" ? "done" : "active");
        }
        if (event.redirect_url) {
            redirectUrl = event.redirect_url;
        }
        if (["done", "warning", "error"].includes(event.status)) {
            if (eventSource) eventSource.close();
            if (event.status !== "error" && redirectUrl) {
                window.setTimeout(() => {
                    modal.classList.remove("open");
                    if (window.navigateWithinApp) {
                        window.navigateWithinApp(redirectUrl, { preserveScroll: true });
                        return;
                    }
                    window.location.href = redirectUrl;
                }, 900);
            }
        }
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        openModal();
        try {
            const response = await fetch("/refresh/start", {
                method: "POST",
                body: new FormData(form),
                headers: { "X-Requested-With": "XMLHttpRequest" }
            });
            const payload = await response.json();
            eventSource = new EventSource(`/refresh/events/${payload.job_id}`);
            eventSource.onmessage = (messageEvent) => {
                applyProgress(JSON.parse(messageEvent.data));
            };
            eventSource.onerror = () => {
                if (messageNode) messageNode.textContent = "进度连接中断，但刷新任务可能仍在后端执行。";
                if (nextNode) nextNode.textContent = "可稍后刷新页面查看最新数据。";
                if (eventSource) eventSource.close();
            };
        } catch (error) {
            if (messageNode) messageNode.textContent = "无法启动实时进度刷新，正在使用普通刷新方式。";
            window.setTimeout(() => form.submit(), 800);
        }
    });

    if (closeNode && closeNode.dataset.refreshCloseReady !== "1") {
        closeNode.dataset.refreshCloseReady = "1";
        closeNode.addEventListener("click", () => {
            modal.classList.remove("open");
        });
    }

    const params = new URLSearchParams(window.location.search);
    if (params.get("progress") === "demo") {
        openModal();
        applyProgress({
            status: "running",
            step: 17,
            total: 45,
            stage: "AQI 空气质量",
            message: "正在抓取 成都 的 AQI、PM2.5、PM10 等空气质量数据。",
            next_step: "下一步：抓取 成都 的历史天气归档。"
        });
    }
}

function initCityAutoload() {
    const panel = document.querySelector("[data-city-autoload]");
    if (!panel) return;
    if (panel.dataset.cityAutoloadReady === "1") return;
    panel.dataset.cityAutoloadReady = "1";
    const form = panel.querySelector("[data-city-load-form]");
    const messageNode = panel.querySelector("[data-city-load-message]");
    const barNode = panel.querySelector("[data-city-load-bar]");
    const percentNode = panel.querySelector("[data-city-load-percent]");
    const stageNode = panel.querySelector("[data-city-load-stage]");
    const refreshUrl = panel.dataset.refreshUrl;
    if (!form || !refreshUrl || typeof EventSource === "undefined") return;

    function applyProgress(event) {
        const step = Number(event.step || 1);
        const total = Number(event.total || 4);
        const percent = Math.max(12, Math.min(100, Math.round((step / total) * 100)));
        panel.classList.toggle("is-error", event.status === "error");
        panel.classList.toggle("is-done", ["done", "warning"].includes(event.status));
        if (stageNode) stageNode.textContent = event.stage || (event.status === "error" ? "加载失败" : "正在加载");
        if (barNode) barNode.style.width = `${percent}%`;
        if (percentNode) percentNode.textContent = `${percent}%`;
        if (messageNode) messageNode.textContent = event.message || "";
        if (event.redirect_url && ["done", "warning"].includes(event.status)) {
            window.setTimeout(() => {
                if (window.navigateWithinApp) {
                    window.navigateWithinApp(event.redirect_url, { preserveScroll: true });
                    return;
                }
                window.location.href = event.redirect_url;
            }, 700);
        }
    }

    fetch(refreshUrl, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "XMLHttpRequest" }
    })
        .then((response) => response.json())
        .then((payload) => {
            const eventSource = new EventSource(`/refresh/events/${payload.job_id}`);
            eventSource.onmessage = (messageEvent) => {
                const event = JSON.parse(messageEvent.data);
                applyProgress(event);
                if (["done", "warning", "error"].includes(event.status)) {
                    eventSource.close();
                }
            };
            eventSource.onerror = () => {
                if (messageNode) messageNode.textContent = "加载连接中断，请稍后刷新页面查看结果。";
                eventSource.close();
            };
        })
        .catch(() => {
            if (messageNode) messageNode.textContent = "无法启动城市数据加载，请返回首页重试。";
        });
}

function initPreferenceSliders() {
    const form = document.querySelector("[data-preference-form]");
    if (!form) return;

    const status = form.querySelector("[data-preference-save-status]");
    const sliders = form.querySelectorAll("[data-preference-slider]");
    const resetButton = form.querySelector("[data-preference-reset]");
    let saveTimer = null;
    let lastQuery = new URLSearchParams(new FormData(form)).toString();

    function optionList(slider) {
        try {
            return JSON.parse(slider.dataset.options || "[]");
        } catch (error) {
            return [];
        }
    }

    function setStatus(text, state) {
        if (!status) return;
        status.textContent = text;
        status.classList.toggle("saving", state === "saving");
    }

    function applySliderValue(slider) {
        const row = slider.closest("[data-preference-row]");
        const hidden = row ? row.querySelector("[data-preference-value]") : null;
        const current = row ? row.querySelector("[data-preference-current]") : null;
        const ticks = row ? row.querySelectorAll("[data-preference-tick]") : [];
        const options = optionList(slider);
        const index = Math.max(0, Math.min(options.length - 1, Number(slider.value) || 0));
        const option = options[index];
        if (!option) return;
        if (hidden) hidden.value = option[0];
        if (current) current.textContent = option[1];
        ticks.forEach((tick, tickIndex) => {
            tick.classList.toggle("active", tickIndex === index);
        });
    }

    function submitPreferences(delay) {
        window.clearTimeout(saveTimer);
        setStatus("正在保存...", "saving");
        saveTimer = window.setTimeout(() => {
            const query = new URLSearchParams(new FormData(form)).toString();
            if (query === lastQuery) {
                setStatus("已保存", "saved");
                return;
            }
            lastQuery = query;
            const target = `${form.action}?${query}`;
            if (window.navigateWithinApp) {
                window.navigateWithinApp(target, { preserveScroll: true });
                return;
            }
            window.location.href = target;
        }, delay);
    }

    sliders.forEach((slider) => {
        slider.addEventListener("input", () => {
            applySliderValue(slider);
            submitPreferences(700);
        });
        slider.addEventListener("change", () => {
            applySliderValue(slider);
            submitPreferences(220);
        });
        applySliderValue(slider);
    });

    if (resetButton) {
        resetButton.addEventListener("click", () => {
            sliders.forEach((slider) => {
                const row = slider.closest("[data-preference-row]");
                const hidden = row ? row.querySelector("[data-preference-value]") : null;
                const defaultValue = hidden ? hidden.dataset.defaultValue : "";
                const options = optionList(slider);
                const defaultIndex = Math.max(0, options.findIndex((option) => option[0] === defaultValue));
                slider.value = String(defaultIndex);
                applySliderValue(slider);
            });
            submitPreferences(120);
        });
    }
}

function initCustomSelect(select) {
    if (!select || select.dataset.customSelectReady === "1") return;

    const wrapper = document.createElement("div");
    const button = document.createElement("button");
    const valueNode = document.createElement("span");
    const menu = document.createElement("div");
    const selectId = select.id || select.name || "select";
    const menuId = `custom-${selectId}-${Math.random().toString(36).slice(2)}`;

    wrapper.className = "custom-select";
    button.type = "button";
    button.className = "custom-select-button";
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-label", select.getAttribute("aria-label") || select.name || "选择");
    valueNode.className = "custom-select-value";
    menu.className = "custom-select-menu";
    menu.id = menuId;
    menu.setAttribute("role", "listbox");
    menu.hidden = true;

    function selectedOption() {
        return select.options[select.selectedIndex] || select.options[0];
    }

    function closeMenu() {
        wrapper.classList.remove("open");
        const hostForm = select.closest("form");
        const hostSection = select.closest(".product-section, .hero-panel");
        if (hostForm) hostForm.classList.remove("select-open");
        if (hostSection) hostSection.classList.remove("select-layer-active");
        button.setAttribute("aria-expanded", "false");
        menu.hidden = true;
    }

    function openMenu() {
        document.querySelectorAll(".custom-select.open").forEach((node) => {
            if (node !== wrapper) {
                node.classList.remove("open");
                const openForm = node.closest("form");
                const openSection = node.closest(".product-section, .hero-panel");
                if (openForm) openForm.classList.remove("select-open");
                if (openSection) openSection.classList.remove("select-layer-active");
                const openButton = node.querySelector(".custom-select-button");
                const openMenuNode = node.querySelector(".custom-select-menu");
                if (openButton) openButton.setAttribute("aria-expanded", "false");
                if (openMenuNode) openMenuNode.hidden = true;
            }
        });
        const hostForm = select.closest("form");
        const hostSection = select.closest(".product-section, .hero-panel");
        if (hostForm) hostForm.classList.add("select-open");
        if (hostSection) hostSection.classList.add("select-layer-active");
        wrapper.classList.add("open");
        button.setAttribute("aria-expanded", "true");
        menu.hidden = false;
        const active = menu.querySelector(".selected");
        if (active) active.focus({ preventScroll: true });
    }

    function syncButton() {
        const option = selectedOption();
        valueNode.textContent = option ? option.textContent : "";
        menu.querySelectorAll(".custom-select-option").forEach((item) => {
            const isSelected = item.dataset.value === select.value;
            item.classList.toggle("selected", isSelected);
            item.setAttribute("aria-selected", String(isSelected));
        });
    }

    Array.from(select.options).forEach((option) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "custom-select-option";
        item.dataset.value = option.value;
        item.textContent = option.textContent;
        item.setAttribute("role", "option");
        item.addEventListener("click", () => {
            if (select.value !== option.value) {
                select.value = option.value;
                syncButton();
                select.dispatchEvent(new Event("change", { bubbles: true }));
            }
            closeMenu();
            button.focus({ preventScroll: true });
        });
        menu.appendChild(item);
    });

    button.appendChild(valueNode);
    wrapper.append(button, menu);
    select.classList.add("custom-select-source");
    select.dataset.customSelectReady = "1";
    select.insertAdjacentElement("afterend", wrapper);
    syncButton();

    button.addEventListener("click", () => {
        if (wrapper.classList.contains("open")) {
            closeMenu();
        } else {
            openMenu();
        }
    });

    button.addEventListener("keydown", (event) => {
        if (["ArrowDown", "Enter", " "].includes(event.key)) {
            event.preventDefault();
            openMenu();
        }
    });

    menu.addEventListener("keydown", (event) => {
        const items = Array.from(menu.querySelectorAll(".custom-select-option"));
        const index = items.indexOf(document.activeElement);
        if (event.key === "Escape") {
            event.preventDefault();
            closeMenu();
            button.focus({ preventScroll: true });
        }
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            const direction = event.key === "ArrowDown" ? 1 : -1;
            const next = items[(Math.max(index, 0) + direction + items.length) % items.length];
            if (next) next.focus({ preventScroll: true });
        }
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            if (document.activeElement) document.activeElement.click();
        }
    });

    document.addEventListener("click", (event) => {
        if (!wrapper.contains(event.target)) {
            closeMenu();
        }
    });
}

function initAutoSubmitSelects() {
    const forms = document.querySelectorAll("[data-auto-submit-form]");
    forms.forEach((form) => {
        const selects = form.querySelectorAll("select");
        if (!selects.length) return;

        selects.forEach((select) => {
            initCustomSelect(select);
            select.dataset.previousValue = select.value;
            select.addEventListener("change", () => {
                if (form.classList.contains("is-submitting") || select.value === select.dataset.previousValue) {
                    return;
                }
                select.dataset.previousValue = select.value;
                form.classList.add("is-submitting");
                form.setAttribute("aria-busy", "true");
                if (typeof form.requestSubmit === "function") {
                    form.requestSubmit();
                    return;
                }
                form.submit();
            });
        });
    });
}

function initScrollExperience() {
    if (typeof TW_APP.scrollCleanup === "function") {
        TW_APP.scrollCleanup();
        TW_APP.scrollCleanup = null;
    }
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const sections = document.querySelectorAll(".main-content > section, .main-content > div");
    sections.forEach((section) => {
        section.classList.add("reveal");
    });

    if (reduceMotion || typeof IntersectionObserver === "undefined") {
        sections.forEach((section) => section.classList.add("is-visible"));
        return;
    }

    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.add("is-visible");
                observer.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.14,
        rootMargin: "0px 0px -8% 0px"
    });

    sections.forEach((section, index) => {
        section.style.transitionDelay = `${Math.min(index * 45, 180)}ms`;
        observer.observe(section);
    });

    const heroVisual = document.querySelector("[data-parallax-visual]");
    if (!heroVisual) {
        TW_APP.scrollCleanup = () => observer.disconnect();
        return;
    }
    let ticking = false;
    function updateParallax() {
        const rect = heroVisual.getBoundingClientRect();
        const progress = Math.max(-1, Math.min(1, rect.top / window.innerHeight));
        heroVisual.style.transform = `translateY(${progress * -10}px) scale(${1 + Math.abs(progress) * 0.012})`;
        ticking = false;
    }
    const onScroll = () => {
        if (!ticking) {
            window.requestAnimationFrame(updateParallax);
            ticking = true;
        }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    TW_APP.scrollCleanup = () => {
        observer.disconnect();
        window.removeEventListener("scroll", onScroll);
    };
    updateParallax();
}

function executeInlinePageScripts(nextDocument) {
    const scripts = Array.from(nextDocument.body.querySelectorAll("script:not([src])"));
    scripts.forEach((script) => {
        const executable = document.createElement("script");
        executable.textContent = script.textContent;
        document.body.appendChild(executable);
        executable.remove();
    });
}

function replaceFlashStack(nextDocument) {
    const currentTopbar = document.querySelector(".topbar");
    const currentFlash = document.querySelector(".flash-stack");
    const nextFlash = nextDocument.querySelector(".flash-stack");

    if (currentFlash) currentFlash.remove();
    if (nextFlash && currentTopbar) {
        currentTopbar.insertAdjacentElement("afterend", document.importNode(nextFlash, true));
    }
}

async function navigateWithinApp(url, options = {}) {
    const target = new URL(url, window.location.href);
    if (target.origin !== window.location.origin) {
        window.location.href = target.toString();
        return false;
    }

    const sameDocument =
        target.pathname === window.location.pathname &&
        target.search === window.location.search &&
        target.hash;
    if (sameDocument) {
        const anchor = document.querySelector(target.hash);
        if (anchor) anchor.scrollIntoView({ behavior: "smooth", block: "start" });
        history.pushState({}, "", target.toString());
        return true;
    }

    if (TW_APP.routeController) {
        TW_APP.routeController.abort();
    }
    const routeController = new AbortController();
    TW_APP.routeController = routeController;

    const main = document.querySelector(".main-content");
    const previousScrollY = window.scrollY;
    if (TW_APP.currentUrl) {
        TW_APP.scrollPositions[TW_APP.currentUrl] = previousScrollY;
    }
    document.documentElement.classList.add("is-route-loading");
    if (main) main.classList.add("is-route-loading");

    try {
        const response = await fetch(target.toString(), {
            headers: {
                "Accept": "text/html",
                "X-Requested-With": "XMLHttpRequest"
            },
            signal: routeController.signal
        });
        const contentType = response.headers.get("content-type") || "";
        if (!response.ok || !contentType.includes("text/html")) {
            throw new Error(`Navigation failed: ${response.status}`);
        }

        const nextDocument = new DOMParser().parseFromString(await response.text(), "text/html");
        const nextMain = nextDocument.querySelector(".main-content");
        const currentMain = document.querySelector(".main-content");
        if (!nextMain || !currentMain) {
            throw new Error("Response did not include main content.");
        }

        disposeRenderedCharts();

        const nextTopbar = nextDocument.querySelector(".topbar");
        const currentTopbar = document.querySelector(".topbar");
        if (nextTopbar && currentTopbar) {
            currentTopbar.replaceWith(document.importNode(nextTopbar, true));
        }

        document.title = nextDocument.title || document.title;
        replaceFlashStack(nextDocument);
        currentMain.className = nextMain.className;
        currentMain.innerHTML = nextMain.innerHTML;
        currentMain.classList.remove("page-transition");
        void currentMain.offsetWidth;
        currentMain.classList.add("page-transition");

        if (options.replaceHistory) {
            history.replaceState({}, "", target.toString());
        } else if (!options.skipHistory) {
            history.pushState({}, "", target.toString());
        }
        TW_APP.currentUrl = target.toString();
        initPage();
        executeInlinePageScripts(nextDocument);

        window.requestAnimationFrame(() => {
            if (options.preserveScroll) {
                window.scrollTo(0, previousScrollY);
                return;
            }
            if (options.restoreScroll && TW_APP.scrollPositions[target.toString()] !== undefined) {
                window.scrollTo(0, TW_APP.scrollPositions[target.toString()]);
                return;
            }
            if (target.hash) {
                const anchor = document.querySelector(target.hash);
                if (anchor) {
                    anchor.scrollIntoView({ behavior: "smooth", block: "start" });
                    return;
                }
            }
            window.scrollTo(0, 0);
        });
        return true;
    } catch (error) {
        if (error.name === "AbortError") return false;
        window.location.href = target.toString();
        return false;
    } finally {
        if (TW_APP.routeController === routeController) {
            document.documentElement.classList.remove("is-route-loading");
            const currentMain = document.querySelector(".main-content");
            if (currentMain) currentMain.classList.remove("is-route-loading");
            TW_APP.routeController = null;
        }
    }
}

function initEnhancedNavigation() {
    if (TW_APP.navigationReady) return;
    TW_APP.navigationReady = true;
    window.history.scrollRestoration = "manual";
    window.navigateWithinApp = navigateWithinApp;

    document.addEventListener("click", (event) => {
        const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
        if (!link || event.defaultPrevented || event.button !== 0) return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        if (link.target && link.target !== "_self") return;
        if (link.hasAttribute("download") || link.dataset.noPjax === "1") return;

        const target = new URL(link.href, window.location.href);
        if (target.origin !== window.location.origin) return;
        if (target.pathname === window.location.pathname && target.search === window.location.search && target.hash) return;

        event.preventDefault();
        navigateWithinApp(target.toString());
    });

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || form.dataset.noPjax === "1") return;
        const method = (form.method || "get").toLowerCase();
        if (method !== "get") return;

        const target = new URL(form.action || window.location.href, window.location.href);
        if (target.origin !== window.location.origin) return;
        target.search = new URLSearchParams(new FormData(form)).toString();

        const preserveScroll =
            form.hasAttribute("data-auto-submit-form") ||
            form.hasAttribute("data-preference-form") ||
            target.pathname === window.location.pathname;
        event.preventDefault();
        navigateWithinApp(target.toString(), { preserveScroll });
    });

    window.addEventListener("popstate", () => {
        navigateWithinApp(window.location.href, { restoreScroll: true, skipHistory: true });
    });
}

function initPage() {
    initCitySuggestions();
    initRefreshProgress();
    initCityAutoload();
    initPreferenceSliders();
    initAutoSubmitSelects();
    initScrollExperience();
}

function bootApp() {
    TW_APP.currentUrl = window.location.href;
    initAssistant();
    initEnhancedNavigation();
    initPage();
}

document.addEventListener("DOMContentLoaded", bootApp);
