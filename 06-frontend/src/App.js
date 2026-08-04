import React, { useState, useRef, useEffect, useCallback } from 'react';
import AppLayout from '@cloudscape-design/components/app-layout';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Input from '@cloudscape-design/components/input';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import TextContent from '@cloudscape-design/components/text-content';
import { ChatBubble, Avatar } from '@cloudscape-design/chat-components';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:3001';

// ── 식당 데이터 ────────────────────────────────────────
const RESTAURANTS = {
  '트라토리아 벨라':    { category: '이탈리안', price: '1.5~5.5만원', location: '강남역',   mood: '로맨틱·데이트' },
  '스시 오마카세 하루': { category: '일식',     price: '6~15만원',   location: '압구정역', mood: '프리미엄·접대' },
  '강남 한우명가':     { category: '한식',     price: '3.5~7만원',  location: '강남역',   mood: '회식·가족모임' },
  '딤섬하우스 강남':   { category: '중식',     price: '1~3.5만원',  location: '강남역',   mood: '캐주얼·점심' },
  '르 비스트로':       { category: '프렌치',   price: '5~8만원',    location: '압구정역', mood: '기념일·프로포즈' },
  '미소라멘 강남점':   { category: '라멘',     price: '1~1.3만원',  location: '강남역',   mood: '혼밥·가성비' },
  '더 그린 키친':      { category: '채식/비건', price: '1.2~1.8만원', location: '신논현역', mood: '건강·캐주얼' },
  '서울갈비 강남본점': { category: '한식',     price: '1.5~4.5만원', location: '역삼역',  mood: '대형회식·40명룸' },
};

const TOOL_ICONS = {
  search_restaurants: '🔍',
  get_menu: '📋',
  check_reservation: '📅',
  create_reservation: '✅',
  estimate_cost: '💰',
  WebSearch: '🌐',
  'web-search-tool___WebSearch': '🌐',
};

// ── 유틸 ──────────────────────────────────────────────
function generateSessionId() {
  // runtimeSessionId 최소 33자 요구사항 충족
  const a = Math.random().toString(36).slice(2, 12);
  const b = Date.now().toString(36);
  const c = Math.random().toString(36).slice(2, 12);
  return `${a}-${b}-${c}`;
}

function loadSessions() {
  try {
    return JSON.parse(localStorage.getItem('dc_sessions') || '[]');
  } catch { return []; }
}

function saveSessions(sessions) {
  localStorage.setItem('dc_sessions', JSON.stringify(sessions));
}

function loadSession(sessionId) {
  try {
    return JSON.parse(localStorage.getItem(`dc_session_${sessionId}`) || 'null');
  } catch { return null; }
}

function saveSession(sessionId, data) {
  localStorage.setItem(`dc_session_${sessionId}`, JSON.stringify(data));
}

function deleteSession(sessionId) {
  localStorage.removeItem(`dc_session_${sessionId}`);
}

// ── 식당 카드 컴포넌트 ─────────────────────────────────
function RestaurantCards({ text, toolCalls }) {
  const hasSearch = toolCalls?.some(tc => tc.name === 'search_restaurants');
  if (!hasSearch) return null;

  const mentioned = Object.keys(RESTAURANTS).filter(name => text.includes(name));
  if (!mentioned.length) return null;

  return (
    <div style={{ marginTop: '12px' }}>
      <div style={{ fontWeight: 'bold', marginBottom: '8px', fontSize: '14px' }}>🏪 식당 상세 정보</div>
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        {mentioned.slice(0, 6).map(name => {
          const info = RESTAURANTS[name];
          return (
            <div key={name} style={{
              border: '1px solid #e0e0e0', borderRadius: '8px', padding: '12px',
              background: '#fafafa', minWidth: '160px', maxWidth: '200px', fontSize: '13px',
            }}>
              <div style={{ fontWeight: 'bold', marginBottom: '6px' }}>{name}</div>
              <div>🏷️ {info.category}</div>
              <div>💰 {info.price}</div>
              <div>📍 {info.location}</div>
              <div>✨ {info.mood}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── 사이드바 컴포넌트 ─────────────────────────────────
function Sidebar({
  actorId, setActorId,
  currentSessionId, sessions, sessionLabel, setSessionLabel,
  onNewSession, onSwitchSession, onDeleteSession,
  toolLogs, memories, fetchMemories,
}) {
  return (
    <div style={{ padding: '16px', height: '100%', overflowY: 'auto', fontSize: '13px' }}>
      {/* 사용자 ID */}
      <div style={{ marginBottom: '16px' }}>
        <div style={{ fontWeight: 'bold', marginBottom: '6px' }}>🍽️ DiningConcierge</div>
        <div style={{ marginBottom: '4px', color: '#666' }}>사용자 ID</div>
        <Input
          value={actorId}
          onChange={({ detail }) => setActorId(detail.value)}
          placeholder="user-taemin"
        />
      </div>

      <hr style={{ border: 'none', borderTop: '1px solid #e0e0e0', margin: '12px 0' }} />

      {/* 세션 관리 */}
      <div style={{ marginBottom: '16px' }}>
        <div style={{ fontWeight: 'bold', marginBottom: '8px' }}>💬 세션 관리</div>
        <div style={{ marginBottom: '6px', color: '#666', fontSize: '12px' }}>
          현재: <code style={{ background: '#f0f0f0', padding: '1px 4px', borderRadius: '3px' }}>
            {currentSessionId.slice(0, 14)}...
          </code>
        </div>
        <div style={{ marginBottom: '6px' }}>
          <Input
            value={sessionLabel}
            onChange={({ detail }) => setSessionLabel(detail.value)}
            placeholder="세션 이름 (선택)"
          />
        </div>
        <Button onClick={onNewSession} variant="primary" fullWidth>🆕 새 세션</Button>

        {sessions.length > 0 && (
          <div style={{ marginTop: '10px' }}>
            <div style={{ color: '#666', marginBottom: '4px' }}>저장된 세션</div>
            {sessions.map(s => (
              <div key={s.id} style={{
                display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '4px',
              }}>
                <Button
                  onClick={() => onSwitchSession(s.id)}
                  variant={s.id === currentSessionId ? 'primary' : 'normal'}
                  fullWidth
                  disabled={s.id === currentSessionId}
                >
                  {s.label || s.id.slice(0, 10) + '...'} ({s.msgCount}턴)
                </Button>
                <Button
                  onClick={() => onDeleteSession(s.id)}
                  variant="icon"
                  iconName="remove"
                  ariaLabel="세션 삭제"
                />
              </div>
            ))}
          </div>
        )}
      </div>

      <hr style={{ border: 'none', borderTop: '1px solid #e0e0e0', margin: '12px 0' }} />

      {/* Memory 현황 */}
      <div style={{ marginBottom: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <div style={{ fontWeight: 'bold' }}>🧠 Memory 현황</div>
          <Button onClick={() => fetchMemories(actorId)} variant="icon" iconName="refresh" ariaLabel="Memory 새로고침" />
        </div>
        {memories.conversations?.length > 0 && (
          <ExpandableSection headerText={`💬 대화 기록 (${Math.floor(memories.conversations.length / 2)}턴)`}>
            {memories.conversations.slice(-6).map((c, i) => (
              <div key={i} style={{ marginBottom: '4px', fontSize: '12px' }}>
                <span style={{ color: c.role === 'USER' ? '#0066cc' : '#555' }}>
                  {c.role === 'USER' ? '👤' : '🤖'}
                </span> {c.text?.slice(0, 60)}{c.text?.length > 60 ? '...' : ''}
              </div>
            ))}
          </ExpandableSection>
        )}
        {memories.preferences?.length > 0 && (
          <ExpandableSection headerText={`❤️ 추출된 취향 (${memories.preferences.length}개)`} defaultExpanded>
            {memories.preferences.map((r, i) => (
              <div key={i} style={{ marginBottom: '4px', fontSize: '12px' }}>• {r.slice(0, 80)}</div>
            ))}
          </ExpandableSection>
        )}
        {memories.facts?.length > 0 && (
          <ExpandableSection headerText={`📝 추출된 사실 (${memories.facts.length}개)`}>
            {memories.facts.map((r, i) => (
              <div key={i} style={{ marginBottom: '4px', fontSize: '12px' }}>• {r.slice(0, 80)}</div>
            ))}
          </ExpandableSection>
        )}
        {!memories.conversations?.length && !memories.preferences?.length && (
          <div style={{ color: '#888', fontSize: '12px' }}>
            💡 대화하면 Memory에 자동 저장됩니다
          </div>
        )}
      </div>

      <hr style={{ border: 'none', borderTop: '1px solid #e0e0e0', margin: '12px 0' }} />

      {/* 도구 호출 로그 */}
      <div>
        <div style={{ fontWeight: 'bold', marginBottom: '8px' }}>🔧 도구 호출 로그</div>
        {toolLogs.length > 0 ? (
          toolLogs.slice(-15).map((log, i) => (
            <div key={i} style={{ marginBottom: '6px', fontSize: '12px' }}>
              <div>
                <code style={{ background: '#f0f0f0', padding: '1px 4px', borderRadius: '3px' }}>
                  #{log.order}
                </code>{' '}
                {TOOL_ICONS[log.name] || '🔧'} <strong>{log.name}</strong>
              </div>
              {log.input && Object.keys(log.input).length > 0 && (
                <div style={{ color: '#666', paddingLeft: '8px' }}>
                  → {Object.entries(log.input).slice(0, 2).map(([k, v]) => `${k}=${v}`).join(', ').slice(0, 60)}
                </div>
              )}
            </div>
          ))
        ) : (
          <div style={{ color: '#888', fontSize: '12px' }}>아직 도구 호출이 없습니다</div>
        )}
      </div>
    </div>
  );
}

// ── 메인 App ──────────────────────────────────────────
function App() {
  const [actorId, setActorId] = useState('user-taemin');
  const [currentSessionId, setCurrentSessionId] = useState(generateSessionId);
  const [sessionLabel, setSessionLabel] = useState('');
  const [sessions, setSessions] = useState(loadSessions);
  const [messages, setMessages] = useState([]);
  const [toolLogs, setToolLogs] = useState([]);
  const [memories, setMemories] = useState({ conversations: [], preferences: [], facts: [] });
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);

  // Memory 현황 조회
  const fetchMemories = useCallback(async (aid) => {
    try {
      const resp = await fetch(`${API_URL}/memory?actor_id=${encodeURIComponent(aid)}`);
      if (resp.ok) {
        const data = await resp.json();
        setMemories(prev => ({
          ...prev,
          preferences: data.preferences || [],
          facts: data.facts || [],
        }));
      }
    } catch (e) {
      console.log('Memory 조회 실패:', e);
    }
  }, []);

  useEffect(() => {
    fetchMemories(actorId);
  }, [actorId, fetchMemories]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 세션 파일에서 messages 복원
  const switchSession = useCallback((sessionId) => {
    // 현재 세션 저장
    if (messages.length > 0) {
      saveSession(currentSessionId, { messages, sessionLabel });
      const updated = sessions.map(s =>
        s.id === currentSessionId ? { ...s, label: sessionLabel, msgCount: Math.floor(messages.length / 2) } : s
      );
      setSessions(updated);
      saveSessions(updated);
    }
    // 선택 세션 로드
    const data = loadSession(sessionId);
    setCurrentSessionId(sessionId);
    setMessages(data?.messages || []);
    setSessionLabel(data?.label || '');
    setToolLogs([]);
  }, [currentSessionId, messages, sessionLabel, sessions]);

  const handleNewSession = useCallback(() => {
    // 현재 세션 저장
    if (messages.length > 0) {
      saveSession(currentSessionId, { messages, sessionLabel });
      const existingIdx = sessions.findIndex(s => s.id === currentSessionId);
      const sessionEntry = { id: currentSessionId, label: sessionLabel, msgCount: Math.floor(messages.length / 2) };
      let updated;
      if (existingIdx >= 0) {
        updated = sessions.map((s, i) => i === existingIdx ? sessionEntry : s);
      } else {
        updated = [sessionEntry, ...sessions];
      }
      setSessions(updated);
      saveSessions(updated);
    }
    const newId = generateSessionId();
    setCurrentSessionId(newId);
    setMessages([]);
    setToolLogs([]);
    setSessionLabel('');
  }, [currentSessionId, messages, sessionLabel, sessions]);

  const handleDeleteSession = useCallback((sessionId) => {
    deleteSession(sessionId);
    const updated = sessions.filter(s => s.id !== sessionId);
    setSessions(updated);
    saveSessions(updated);
    if (sessionId === currentSessionId) {
      setCurrentSessionId(generateSessionId());
      setMessages([]);
      setToolLogs([]);
      setSessionLabel('');
    }
  }, [sessions, currentSessionId]);

  // 대화 컨텍스트 생성 (최근 3턴)
  const buildConversationContext = (msgs) => {
    if (!msgs.length) return '';
    const recent = msgs.slice(-6);
    const lines = recent.map(m => `${m.role === 'user' ? '사용자' : '어시스턴트'}: ${m.content.slice(0, 200)}`);
    return `[이전 대화]\n${lines.join('\n')}\n\n[현재 질문]\n`;
  };

  const sendMessage = async () => {
    const text = inputValue.trim();
    if (!text || loading) return;

    const userMsg = { role: 'user', content: text };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setInputValue('');
    setLoading(true);

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: currentSessionId,
          actor_id: actorId,
          conversation_context: buildConversationContext(messages),
        }),
      });
      const data = await response.json();
      const reply = data.reply || '응답을 생성하지 못했습니다.';
      const toolCalls = data.tool_calls || [];

      const assistantMsg = { role: 'assistant', content: reply, toolCalls };
      const finalMessages = [...updatedMessages, assistantMsg];
      setMessages(finalMessages);

      // 도구 로그 업데이트
      if (toolCalls.length > 0) {
        setToolLogs(prev => [...prev, ...toolCalls.map(tc => ({
          ...tc,
          order: prev.length + tc.order,
        }))]);
      }

      // 세션 자동 저장
      saveSession(currentSessionId, { messages: finalMessages, label: sessionLabel });
      const existingIdx = sessions.findIndex(s => s.id === currentSessionId);
      const sessionEntry = { id: currentSessionId, label: sessionLabel, msgCount: Math.floor(finalMessages.length / 2) };
      let updated;
      if (existingIdx >= 0) {
        updated = sessions.map((s, i) => i === existingIdx ? sessionEntry : s);
      } else {
        updated = [sessionEntry, ...sessions];
      }
      setSessions(updated);
      saveSessions(updated);

      // Memory 현황 업데이트 (대화 기록 + 새로고침)
      setMemories(prev => ({
        ...prev,
        conversations: [...(prev.conversations || []),
          { role: 'USER', text },
          { role: 'ASSISTANT', text: reply },
        ],
      }));
      // 채팅 후 Memory 새로고침 (비동기)
      setTimeout(() => fetchMemories(actorId), 2000);

    } catch (error) {
      const errMsg = { role: 'assistant', content: `오류가 발생했습니다: ${error.message}` };
      setMessages(prev => [...prev, errMsg]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.detail.key === 'Enter' && !e.detail.shiftKey) {
      sendMessage();
    }
  };

  return (
    <AppLayout
      navigation={
        <Sidebar
          actorId={actorId}
          setActorId={setActorId}
          currentSessionId={currentSessionId}
          sessions={sessions}
          sessionLabel={sessionLabel}
          setSessionLabel={setSessionLabel}
          onNewSession={handleNewSession}
          onSwitchSession={switchSession}
          onDeleteSession={handleDeleteSession}
          toolLogs={toolLogs}
          memories={memories}
          fetchMemories={fetchMemories}
        />
      }
      content={
        <Container
          header={
            <Header
              variant="h1"
              description={`세션: ${currentSessionId.slice(0, 16)}... | 사용자: ${actorId}`}
              actions={
                <SpaceBetween direction="horizontal" size="xs">
                  {toolLogs.length > 0 && (
                    <Badge color="blue">🔧 {toolLogs.length}회 도구 호출</Badge>
                  )}
                </SpaceBetween>
              }
            >
              🍽️ 다이닝 컨시어지
            </Header>
          }
        >
          <SpaceBetween size="l">
            {/* 채팅 영역 */}
            <div style={{ height: '60vh', overflowY: 'auto', padding: '8px' }}>
              <SpaceBetween size="s">
                {messages.length === 0 && (
                  <Box textAlign="center" color="text-body-secondary" padding="xl">
                    <TextContent>
                      <p>안녕하세요! 강남 식당 추천 AI 어시스턴트입니다.</p>
                      <p style={{ fontSize: '13px', color: '#888' }}>
                        식당 추천, 메뉴 조회, 예약, 비용 산정을 도와드립니다.
                      </p>
                    </TextContent>
                  </Box>
                )}
                {messages.map((msg, index) => (
                  <div key={index}>
                    <ChatBubble
                      type={msg.role === 'user' ? 'outgoing' : 'incoming'}
                      ariaLabel={`${msg.role === 'user' ? '사용자' : 'AI'} 메시지`}
                      avatar={
                        <Avatar
                          color={msg.role === 'user' ? 'default' : 'gen-ai'}
                          ariaLabel={msg.role === 'user' ? '사용자' : 'AI'}
                          initials={msg.role === 'user' ? '나' : 'AI'}
                          iconName={msg.role === 'user' ? 'user-profile' : 'gen-ai'}
                        />
                      }
                    >
                      <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
                    </ChatBubble>
                    {msg.role === 'assistant' && msg.toolCalls?.length > 0 && (
                      <div style={{ marginLeft: '48px', marginTop: '4px' }}>
                        <SpaceBetween direction="horizontal" size="xs">
                          {msg.toolCalls.map((tc, i) => (
                            <Badge key={i} color="blue">
                              {TOOL_ICONS[tc.name] || '🔧'} {tc.name}
                            </Badge>
                          ))}
                        </SpaceBetween>
                        <RestaurantCards text={msg.content} toolCalls={msg.toolCalls} />
                      </div>
                    )}
                  </div>
                ))}
                {loading && (
                  <ChatBubble
                    type="incoming"
                    ariaLabel="AI 응답 로딩 중"
                    avatar={
                      <Avatar color="gen-ai" ariaLabel="AI" iconName="gen-ai" loading={true} />
                    }
                  >
                    답변을 준비하고 있습니다...
                  </ChatBubble>
                )}
                <div ref={messagesEndRef} />
              </SpaceBetween>
            </div>

            {/* 입력 영역 */}
            <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end' }}>
              <div style={{ flex: 1 }}>
                <Input
                  value={inputValue}
                  onChange={({ detail }) => setInputValue(detail.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="식당 추천, 예약, 메뉴 조회... (Enter로 전송)"
                  disabled={loading}
                />
              </div>
              <Button
                variant="primary"
                onClick={sendMessage}
                loading={loading}
                disabled={!inputValue.trim()}
                iconName="angle-right-double"
              >
                전송
              </Button>
            </div>
          </SpaceBetween>
        </Container>
      }
      navigationWidth={300}
    />
  );
}

export default App;
