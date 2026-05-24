function baseChartOption(title) {
    return {
        backgroundColor: "transparent",
        title: {
            text: title || "",
            left: "center",
            textStyle: {
                fontFamily: "Georgia, serif",
                fontSize: 16,
                fontWeight: 600,
                color: "#192127"
            }
        },
        tooltip: { trigger: "axis" },
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
    option.xAxis = { type: "category", data: payload.labels, axisLabel: { color: "#48545a", rotate: 20 } };
    option.yAxis = { type: "value", axisLabel: { color: "#48545a" } };
    option.series = [{
        type: "bar",
        data: payload.values,
        barWidth: 28,
        itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: "#d98c3f" },
                { offset: 1, color: "#165a72" }
            ]),
            borderRadius: [10, 10, 0, 0]
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
    option.xAxis = { type: "category", data: payload.labels, axisLabel: { color: "#48545a" } };
    option.yAxis = { type: "value", axisLabel: { color: "#48545a" } };
    option.series = payload.series.map((item, index) => ({
        name: item.name,
        type: "bar",
        data: item.values,
        itemStyle: {
            color: index === 0 ? "#165a72" : "#d98c3f",
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
    option.xAxis = { type: "category", data: payload.labels, axisLabel: { color: "#48545a" } };
    option.yAxis = { type: "value", axisLabel: { color: "#48545a" } };
    option.series = payload.series.map((item, index) => ({
        name: item.name,
        type: "line",
        smooth: true,
        data: item.values,
        symbolSize: 8,
        lineStyle: { width: 3 },
        itemStyle: { color: index === 0 ? "#165a72" : index === 1 ? "#d98c3f" : "#5b7f3a" },
        areaStyle: index === 0 ? { color: "rgba(22,90,114,0.08)" } : undefined
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
                borderColor: "rgba(22,90,114,0.18)",
                fillerColor: "rgba(22,90,114,0.12)",
                handleStyle: { color: "#165a72" },
                textStyle: { color: "#5c686d" }
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

function initCitySearch() {
    const form = document.querySelector("[data-city-search-form]");
    if (!form) return;
    const input = form.querySelector("[data-city-search-input]");
    const suggestionsNode = form.querySelector("[data-city-search-suggestions]");
    const emptyNode = form.querySelector("[data-city-search-empty]");
    if (!input || !suggestionsNode) return;

    const searchUrl = form.dataset.searchUrl;
    const refreshUrl = form.dataset.refreshUrl;
    let timer = null;
    let activeController = null;

    function hiddenPreferences() {
        return Array.from(form.querySelectorAll('input[type="hidden"]')).map((node) => [node.name, node.value]);
    }

    function submitCityRefresh(city) {
        const postForm = document.createElement("form");
        postForm.method = "POST";
        postForm.action = refreshUrl;
        const fields = {
            slug: city.slug,
            name: city.name,
            latitude: city.latitude,
            longitude: city.longitude
        };
        Object.entries(fields).forEach(([name, value]) => {
            const node = document.createElement("input");
            node.type = "hidden";
            node.name = name;
            node.value = value;
            postForm.appendChild(node);
        });
        hiddenPreferences().forEach(([name, value]) => {
            const node = document.createElement("input");
            node.type = "hidden";
            node.name = name;
            node.value = value;
            postForm.appendChild(node);
        });
        document.body.appendChild(postForm);
        postForm.submit();
    }

    function renderSuggestions(results) {
        suggestionsNode.innerHTML = "";
        if (!results.length) {
            if (emptyNode) emptyNode.hidden = false;
            return;
        }
        if (emptyNode) emptyNode.hidden = true;
        results.forEach((city) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "search-suggestion";
            const title = document.createElement("strong");
            title.textContent = city.display_name || city.name;
            const meta = document.createElement("span");
            meta.textContent = `${city.source || "城市联想"} · 点击刷新并查看`;
            button.append(title, meta);
            button.addEventListener("click", () => submitCityRefresh(city));
            suggestionsNode.appendChild(button);
        });
    }

    async function fetchSuggestions(query) {
        if (activeController) activeController.abort();
        activeController = new AbortController();
        const response = await fetch(`${searchUrl}?q=${encodeURIComponent(query)}`, {
            signal: activeController.signal,
            headers: { "X-Requested-With": "XMLHttpRequest" }
        });
        const payload = await response.json();
        renderSuggestions(payload.results || []);
    }

    input.addEventListener("input", () => {
        const query = input.value.trim();
        window.clearTimeout(timer);
        if (!query) {
            suggestionsNode.innerHTML = "";
            if (emptyNode) emptyNode.hidden = true;
            return;
        }
        timer = window.setTimeout(() => {
            fetchSuggestions(query).catch((error) => {
                if (error.name !== "AbortError") {
                    suggestionsNode.innerHTML = "";
                    if (emptyNode) emptyNode.hidden = false;
                }
            });
        }, 250);
    });

    if (input.value.trim()) {
        fetchSuggestions(input.value.trim()).catch(() => {});
    }
}

document.addEventListener("DOMContentLoaded", initCitySearch);

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
