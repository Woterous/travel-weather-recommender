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
