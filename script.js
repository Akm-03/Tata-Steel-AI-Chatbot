// --- 1. Session & Auth Management ---
window.onload = () => {
    const activeUser = localStorage.getItem("tsil_auth_token");
    if (activeUser) {
        // User is logged in, show dashboard
        document.getElementById("login-overlay").style.display = "none";
        document.getElementById("dashboard").style.display = "flex";
        document.getElementById("user-display").innerText = "Badge: " + activeUser;
        loadChatHistory();
    }
};

function handleLogin() {
    const badge = document.getElementById("badge-input").value.trim();
    const pwd = document.getElementById("password-input").value.trim();
    
    // Mock Authentication (Require at least 4 chars)
    if (badge.length >= 4 && pwd.length >= 4) {
        localStorage.setItem("tsil_auth_token", badge);
        location.reload(); 
    } else {
        document.getElementById("login-error").style.display = "block";
    }
}

function handleLogout() {
    localStorage.removeItem("tsil_auth_token");
    localStorage.removeItem("tsil_chat_history"); // Clear chat on logout for security
    location.reload();
}

// --- 2. Chat Logic & API Integration ---
function handleEnter(event) {
    if (event.key === "Enter") sendMessage();
}

function sendQuickPrompt(text) {
    document.getElementById("chat-input").value = text;
    sendMessage();
}

async function sendMessage() {
    const inputField = document.getElementById("chat-input");
    const text = inputField.value.trim();
    if (!text) return;

    // Show user message
    appendMessage("user", text);
    saveToHistory("user", text);
    inputField.value = "";

    // Show temporary typing indicator
    const thinkingId = appendMessage("bot", "<i>Querying Database...</i>");

    try {
        // Communicate with FastAPI Backend
        const response = await fetch("http://localhost:8000/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text })
        });

        if (!response.ok) throw new Error("Backend connection failed.");
        const data = await response.json();

        // 1. Prepare base response html
        let finalHtml = `<div>${data.answer}</div>`;

        // 2. Check if the backend sent chart data, create a canvas if true
        let canvasId = null;
        if (data.chart_data && data.chart_data.length > 0) {
            canvasId = "chart-" + Date.now();
            finalHtml += `<canvas id="${canvasId}" style="max-width:100%; max-height:250px; margin-top:15px;"></canvas>`;
        }

        // 3. Add the SQL diagnostic box
        finalHtml += `<div class="sql-box"><b>Generated Query:</b><br>${data.generated_query}</div>`;
        
        // 4. Update the chat bubble on the screen
        document.getElementById(thinkingId).innerHTML = finalHtml;
        saveToHistory("bot", finalHtml);

        // 5. Draw the chart using Chart.js AFTER the canvas is loaded on the screen
        if (canvasId) {
            setTimeout(() => {
                const ctx = document.getElementById(canvasId).getContext('2d');
                new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: data.chart_data.map(d => d.PARAMETER_TYPE),
                        datasets: [{
                            label: 'Deviation Counts',
                            data: data.chart_data.map(d => parseInt(d.COUNT)),
                            backgroundColor: '#0ea5e9', // Matches your Tata Steel blue theme
                            borderRadius: 4
                        }]
                    },
                    options: {
                        responsive: true,
                        plugins: {
                            legend: { display: false } // Hides the unnecessary legend
                        },
                        scales: {
                            y: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                            x: { ticks: { color: '#94a3b8' }, grid: { display: false } }
                        }
                    }
                });
            }, 150); // Slight delay ensures HTML is fully rendered before drawing
        }

    } catch (error) {
        document.getElementById(thinkingId).innerHTML = `<span style="color:#ef4444;">⚠️ Error: Could not connect to the AI Backend. Ensure FastAPI is running.</span>`;
    }
}

// --- 3. UI Helpers & Persistent Memory ---
function appendMessage(role, content) {
    const chatHistory = document.getElementById("chat-history");
    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${role === "user" ? "user-msg" : "bot-msg"}`;
    msgDiv.innerHTML = content;
    
    const uniqueId = "msg-" + Date.now();
    msgDiv.id = uniqueId;
    
    chatHistory.appendChild(msgDiv);
    
    // Auto-scroll to the newest message
    chatHistory.scrollTop = chatHistory.scrollHeight;
    
    return uniqueId;
}

function saveToHistory(role, content) {
    let history = JSON.parse(localStorage.getItem("tsil_chat_history")) || [];
    history.push({ role, content });
    localStorage.setItem("tsil_chat_history", JSON.stringify(history));
}

function loadChatHistory() {
    let history = JSON.parse(localStorage.getItem("tsil_chat_history")) || [];
    // Skip the first default welcome message if history exists
    if (history.length > 0) {
        document.getElementById("chat-history").innerHTML = ""; 
    }
    history.forEach(msg => {
        appendMessage(msg.role, msg.content);
    });
}