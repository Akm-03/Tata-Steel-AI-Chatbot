import React, { useState, useRef, useEffect, useCallback } from 'react';

// ── Simple markdown-ish renderer for bot responses ──────────────
function renderMarkdown(text) {
  if (!text) return null;

  // Split into lines and process
  const lines = text.split('\n');
  const elements = [];
  let i = 0;

  // Check if we have a markdown table
  const tableStart = lines.findIndex(l => l.trim().startsWith('|'));
  if (tableStart !== -1) {
    // Render lines before table
    const before = lines.slice(0, tableStart).join('\n');
    if (before.trim()) {
      elements.push(...renderTextBlocks(before, 'pre-table'));
    }

    // Find table end
    let tableEnd = tableStart;
    while (tableEnd < lines.length && lines[tableEnd].trim().startsWith('|')) {
      tableEnd++;
    }

    // Parse table
    const tableLines = lines.slice(tableStart, tableEnd).filter(l => !l.match(/^\|\s*[-:]+/));
    if (tableLines.length > 0) {
      const headers = tableLines[0].split('|').filter(c => c.trim()).map(c => c.trim());
      const rows = tableLines.slice(1).map(r => r.split('|').filter(c => c.trim()).map(c => c.trim()));
      elements.push(
        <table key="table">
          <thead>
            <tr>{headers.map((h, j) => <th key={j}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri}>{row.map((cell, ci) => <td key={ci}>{cell}</td>)}</tr>
            ))}
          </tbody>
        </table>
      );
    }

    // Render lines after table
    const after = lines.slice(tableEnd).join('\n');
    if (after.trim()) {
      elements.push(...renderTextBlocks(after, 'post-table'));
    }

    return elements;
  }

  return renderTextBlocks(text, 'full');
}

function renderTextBlocks(text, keyPrefix) {
  const paragraphs = text.split(/\n\n+/);
  return paragraphs.map((para, i) => {
    const trimmed = para.trim();
    if (!trimmed) return null;

    // Check for list items
    if (trimmed.match(/^[-•*]\s/m)) {
      const items = trimmed.split(/\n/).filter(l => l.trim());
      return (
        <ul key={`${keyPrefix}-${i}`}>
          {items.map((item, j) => (
            <li key={j}>{renderInline(item.replace(/^[-•*]\s*/, ''))}</li>
          ))}
        </ul>
      );
    }

    // Check for numbered list
    if (trimmed.match(/^\d+\.\s/m)) {
      const items = trimmed.split(/\n/).filter(l => l.trim());
      return (
        <ol key={`${keyPrefix}-${i}`}>
          {items.map((item, j) => (
            <li key={j}>{renderInline(item.replace(/^\d+\.\s*/, ''))}</li>
          ))}
        </ol>
      );
    }

    // Regular paragraph — preserve line breaks
    const lines = trimmed.split('\n');
    return (
      <p key={`${keyPrefix}-${i}`}>
        {lines.map((line, j) => (
          <React.Fragment key={j}>
            {j > 0 && <br />}
            {renderInline(line)}
          </React.Fragment>
        ))}
      </p>
    );
  }).filter(Boolean);
}

function renderInline(text) {
  // Bold **text** or __text__
  const parts = [];
  const regex = /(\*\*|__)(.*?)\1|(`)(.*?)\3/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    if (match[1]) {
      parts.push(<strong key={match.index}>{match[2]}</strong>);
    } else if (match[3]) {
      parts.push(<code key={match.index}>{match[4]}</code>);
    }
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length > 0 ? parts : text;
}

// ── Quick-action suggestion data ────────────────────────────────
const WELCOME_SUGGESTIONS = [
  { label: '⚡ GMAW arc efficiency today', query: 'What is the arc efficiency for all GMAW machines today?' },
  { label: '🔥 Total LPG consumption by shift', query: 'Total LPG consumption by shift' },
  { label: '📊 CLAD session summary this week', query: 'Show CLAD session summary for this week' },
  { label: '⚠️ Recent deviation events', query: 'Show the latest deviation events across all machines' },
  { label: '🏭 GasCutting productivity', query: 'Show GasCutting productivity metrics' },
  { label: '🌡️ GMAW sensor averages', query: 'Show average welding current, voltage, and gas flow for all GMAW machines' },
];

const QUICK_SUGGESTIONS = [
  'GMAW efficiency by shift',
  'D&H-1 sensor readings',
  'Deviation events today',
  'GasCutting speed analysis',
  'CLAD current and voltage',
];

// ── Timestamp formatter ─────────────────────────────────────────
function formatTime(date) {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ══════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ══════════════════════════════════════════════════════════════════
const TataSteelChatbot = () => {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [showSql, setShowSql] = useState(false);
  const chatEndRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Focus input on load
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSend = useCallback(async (overrideText) => {
    const text = (overrideText || input).trim();
    if (!text || isLoading) return;

    const userMsg = { role: 'user', text, time: new Date() };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);

    try {
      const res = await fetch('http://localhost:8000/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
          show_sql: showSql,
        }),
      });

      const data = await res.json();

      if (data.session_id && !sessionId) {
        setSessionId(data.session_id);
      }

      const botMsg = {
        role: 'bot',
        text: data.response,
        sql: data.sql_used,
        category: data.category,
        time: new Date(),
      };

      setMessages(prev => [...prev, botMsg]);
    } catch (err) {
      setMessages(prev => [
        ...prev,
        {
          role: 'bot',
          text: 'Unable to connect to the backend server. Please ensure the API is running on port 8000.',
          time: new Date(),
          isError: true,
        },
      ]);
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  }, [input, isLoading, sessionId, showSql]);

  const handleClearChat = useCallback(async () => {
    if (sessionId) {
      try {
        await fetch(`http://localhost:8000/session/${sessionId}`, { method: 'DELETE' });
      } catch (e) { /* ignore */ }
    }
    setMessages([]);
    setSessionId(null);
    inputRef.current?.focus();
  }, [sessionId]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const isWelcome = messages.length === 0;

  return (
    <>
      {/* ── Header ──────────────────────────────────────────── */}
      <header className="header" id="chatbot-header">
        <div className="header-brand">
          <div className="header-logo">TS</div>
          <div>
            <div className="header-title">Tata Steel Ops Intelligence</div>
            <div className="header-subtitle">AI-Powered Machine Analytics</div>
          </div>
        </div>
        <div className="header-actions">
          <div className="header-status">
            <span className="status-dot"></span>
            <span>Connected</span>
          </div>
          <button
            className={`btn-icon btn-icon-sql ${showSql ? 'active' : ''}`}
            onClick={() => setShowSql(s => !s)}
            title={showSql ? 'Hide SQL queries' : 'Show SQL queries'}
            id="toggle-sql-btn"
          >
            SQL
          </button>
          <button
            className="btn-icon"
            onClick={handleClearChat}
            title="Clear chat"
            id="clear-chat-btn"
          >
            🗑
          </button>
        </div>
      </header>

      {/* ── Chat / Welcome ──────────────────────────────────── */}
      {isWelcome ? (
        <div className="welcome-container" id="welcome-screen">
          <div className="welcome-icon">🏭</div>
          <h1 className="welcome-title">How can I help you today?</h1>
          <p className="welcome-desc">
            Ask about machine performance, sensor readings, shift efficiency, deviation events,
            or any operational data across GMAW, CLAD, and GasCutting machines.
          </p>
          <div className="welcome-chips">
            {WELCOME_SUGGESTIONS.map((s, i) => (
              <button
                className="welcome-chip"
                key={i}
                onClick={() => handleSend(s.query)}
                id={`welcome-chip-${i}`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="chat-container" id="chat-messages">
          {messages.map((msg, idx) => (
            <div className={`message-row ${msg.role}`} key={idx}>
              <div className={`message-avatar ${msg.role}`}>
                {msg.role === 'bot' ? '🤖' : '👤'}
              </div>
              <div className="message-content">
                <div className={`message-bubble ${msg.role} ${msg.isError ? 'error' : ''}`}>
                  {msg.role === 'bot' ? renderMarkdown(msg.text) : msg.text}
                </div>
                {msg.sql && showSql && (
                  <div className="sql-preview">
                    <div className="sql-preview-label">SQL Query</div>
                    {msg.sql}
                  </div>
                )}
                <div className="message-time">{formatTime(msg.time)}</div>
              </div>
            </div>
          ))}

          {/* Typing indicator */}
          {isLoading && (
            <div className="typing-indicator">
              <div className="message-avatar bot">🤖</div>
              <div className="typing-dots">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          )}

          <div ref={chatEndRef} />
        </div>
      )}

      {/* ── Quick Actions (only when there are messages) ───── */}
      {!isWelcome && !isLoading && (
        <div className="quick-actions" id="quick-actions">
          {QUICK_SUGGESTIONS.map((q, i) => (
            <button
              className="quick-chip"
              key={i}
              onClick={() => handleSend(q)}
              id={`quick-chip-${i}`}
            >
              {q}
            </button>
          ))}
        </div>
      )}

      {/* ── Input Area ──────────────────────────────────────── */}
      <div className="input-area" id="input-area">
        <div className="input-wrapper">
          <input
            ref={inputRef}
            type="text"
            className="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about machine performance, sensor data, shift efficiency..."
            disabled={isLoading}
            id="chat-input"
          />
          <button
            className="send-btn"
            onClick={() => handleSend()}
            disabled={!input.trim() || isLoading}
            title="Send message"
            id="send-btn"
          >
            ➤
          </button>
        </div>
      </div>
    </>
  );
};

export default TataSteelChatbot;