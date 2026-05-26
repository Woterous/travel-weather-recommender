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
    return echarts.init(node);
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

document.addEventListener("DOMContentLoaded", initAssistant);

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

document.addEventListener("DOMContentLoaded", initCitySuggestions);

function initRefreshProgress() {
    const form = document.querySelector(".refresh-form");
    const modal = document.querySelector("[data-refresh-modal]");
    if (!form || !modal || typeof EventSource === "undefined") return;

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

    if (closeNode) {
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

document.addEventListener("DOMContentLoaded", initRefreshProgress);

function initCityAutoload() {
    const panel = document.querySelector("[data-city-autoload]");
    if (!panel) return;
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

document.addEventListener("DOMContentLoaded", initCityAutoload);

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
            window.location.href = `${form.action}?${query}`;
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

document.addEventListener("DOMContentLoaded", initPreferenceSliders);

function initScrollExperience() {
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
    if (!heroVisual) return;
    let ticking = false;
    function updateParallax() {
        const rect = heroVisual.getBoundingClientRect();
        const progress = Math.max(-1, Math.min(1, rect.top / window.innerHeight));
        heroVisual.style.transform = `translateY(${progress * -10}px) scale(${1 + Math.abs(progress) * 0.012})`;
        ticking = false;
    }
    window.addEventListener("scroll", () => {
        if (!ticking) {
            window.requestAnimationFrame(updateParallax);
            ticking = true;
        }
    }, { passive: true });
    updateParallax();
}

document.addEventListener("DOMContentLoaded", initScrollExperience);
