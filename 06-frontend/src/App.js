import React, { useState, useRef, useEffect } from 'react';
import AppLayout from '@cloudscape-design/components/app-layout';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Input from '@cloudscape-design/components/input';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import { ChatBubble, Avatar, LoadingBar } from '@cloudscape-design/chat-components';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:3001';

function App() {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  const sendMessage = async () => {
    const text = inputValue.trim();
    if (!text) return;

    const userMessage = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setLoading(true);

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      const data = await response.json();
      const assistantMessage = { role: 'assistant', content: data.reply };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      const errorMessage = { role: 'assistant', content: '오류가 발생했습니다. 다시 시도해주세요.' };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.detail.key === 'Enter') {
      sendMessage();
    }
  };

  return (
    <AppLayout
      content={
        <Container
          header={<Header variant="h1">AI 식당 추천 채팅</Header>}
        >
          <SpaceBetween size="l">
            <div style={{ height: '500px', overflowY: 'auto', padding: '16px' }}>
              <SpaceBetween size="s">
                {messages.length === 0 && (
                  <Box textAlign="center" color="text-body-secondary" padding="l">
                    안녕하세요! 식당 추천을 도와드리겠습니다. 메시지를 입력해주세요.
                  </Box>
                )}
                {messages.map((msg, index) => (
                  <ChatBubble
                    key={index}
                    type={msg.role === 'user' ? 'outgoing' : 'incoming'}
                    ariaLabel={`${msg.role === 'user' ? '사용자' : 'AI'} 메시지 ${index + 1}`}
                    avatar={
                      <Avatar
                        color={msg.role === 'user' ? 'default' : 'gen-ai'}
                        ariaLabel={msg.role === 'user' ? '사용자 아바타' : 'AI 아바타'}
                        initials={msg.role === 'user' ? '나' : 'AI'}
                        iconName={msg.role === 'user' ? 'user-profile' : 'gen-ai'}
                      />
                    }
                  >
                    {msg.content}
                  </ChatBubble>
                ))}
                {loading && (
                  <ChatBubble
                    type="incoming"
                    ariaLabel="AI 응답 로딩 중"
                    showLoadingBar={true}
                    avatar={
                      <Avatar
                        color="gen-ai"
                        ariaLabel="AI 아바타"
                        iconName="gen-ai"
                        loading={true}
                      />
                    }
                  >
                    응답 중...
                  </ChatBubble>
                )}
                <div ref={messagesEndRef} />
              </SpaceBetween>
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <div style={{ flex: 1 }}>
                <Input
                  value={inputValue}
                  onChange={({ detail }) => setInputValue(detail.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="메시지를 입력하세요"
                  disabled={loading}
                />
              </div>
              <Button
                variant="primary"
                onClick={sendMessage}
                loading={loading}
                disabled={!inputValue.trim()}
              >
                전송
              </Button>
            </div>
          </SpaceBetween>
        </Container>
      }
      navigationHide={true}
      toolsHide={true}
    />
  );
}

export default App;
