import { useState, useRef, useEffect } from 'react'
import { useChat } from '@/hooks/use-foster'
import { GlassCard } from '@/components/ui/glass-card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { toast } from '@/components/ui/toast'
import { motion, AnimatePresence } from 'framer-motion'
import { Send, Bot, User, Sparkles, Lightbulb, Bug, Workflow, MessageSquare } from 'lucide-react'
import type { ChatMessage } from '@/types'

const suggestedPrompts = [
  { icon: Workflow, label: 'What workflows are currently stuck?', action: 'Show me all workflows that are currently stuck or failing' },
  { icon: Bug, label: 'Debug approval process', action: 'Help me debug why an approval is taking too long' },
  { icon: Lightbulb, label: 'Placement suggestions', action: 'What factors should I consider for placement matching?' },
  { icon: Sparkles, label: 'System overview', action: 'Give me a quick overview of the current system status' },
]

function TypingIndicator() {
  return (
    <div className="flex items-start gap-3">
      <div className="w-8 h-8 rounded-lg bg-primary/15 flex items-center justify-center shrink-0">
        <Bot size={16} className="text-primary" />
      </div>
      <div className="glass-card p-3 rounded-tl-none">
        <div className="flex gap-1">
          <span className="w-2 h-2 rounded-full bg-primary/40 animate-bounce" style={{ animationDelay: '0ms' }} />
          <span className="w-2 h-2 rounded-full bg-primary/40 animate-bounce" style={{ animationDelay: '150ms' }} />
          <span className="w-2 h-2 rounded-full bg-primary/40 animate-bounce" style={{ animationDelay: '300ms' }} />
        </div>
      </div>
    </div>
  )
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user'
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`}
    >
      <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
        isUser ? 'bg-accent/15' : 'bg-primary/15'
      }`}>
        {isUser ? <User size={16} className="text-accent" /> : <Bot size={16} className="text-primary" />}
      </div>
      <div className={`max-w-[80%] ${isUser ? 'items-end' : 'items-start'}`}>
        <div className={`glass-card p-3 ${isUser ? 'rounded-tr-none bg-primary/5 border-primary/20' : 'rounded-tl-none'}`}>
          <p className="text-sm text-foreground whitespace-pre-wrap">{message.content}</p>
        </div>
        {message.sources && message.sources.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {message.sources.map((source, i) => (
              <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-glass border border-glass-border text-muted-foreground">
                {source}
              </span>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  )
}

export default function ChatPage() {
  const chatMutation = useChat()
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content: "Hello! I'm your AI orchestration assistant for the Artifex foster care platform. I can help you track workflows, debug issues, and optimize placement matching. What would you like to know?",
      timestamp: new Date().toISOString(),
    },
  ])
  const [input, setInput] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isTyping])

  const handleSend = async (content: string) => {
    if (!content.trim() || isTyping) return

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: content.trim(),
      timestamp: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setIsTyping(true)

    try {
      const result = await chatMutation.mutateAsync({ message: content.trim() })
      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: result.message,
        timestamp: new Date().toISOString(),
        sources: result.sources,
      }
      setMessages((prev) => [...prev, assistantMessage])
    } catch (err) {
      toast({
        title: 'Chat Error',
        description: 'Failed to get response from AI assistant',
        variant: 'error',
      })
    } finally {
      setIsTyping(false)
    }
  }

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-6 h-[calc(100vh-5rem)] flex flex-col">
      <div>
        <h1 className="text-2xl font-bold text-foreground">AI Assistant</h1>
        <p className="text-sm text-muted-foreground mt-1">Conversational AI orchestration assistant</p>
      </div>

      <GlassCard className="flex-1 flex flex-col min-h-0">
        <div className="flex-1 overflow-y-auto px-1 space-y-4 py-2">
          <AnimatePresence>
            {messages.map((msg) => (
              <ChatBubble key={msg.id} message={msg} />
            ))}
          </AnimatePresence>
          {isTyping && <TypingIndicator />}
          <div ref={messagesEndRef} />
        </div>

        {messages.length === 1 && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
            {suggestedPrompts.map((prompt) => (
              <button
                key={prompt.label}
                onClick={() => handleSend(prompt.action)}
                className="flex items-center gap-2 p-3 rounded-lg glass-card text-left hover:bg-glass-hover transition-all cursor-pointer"
              >
                <prompt.icon size={16} className="text-primary shrink-0" />
                <span className="text-xs text-muted-foreground leading-tight">{prompt.label}</span>
              </button>
            ))}
          </div>
        )}

        <div className="flex gap-3 pt-3 border-t border-border">
          <div className="flex-1">
            <Input
              placeholder="Ask about workflows, placements, or system status..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend(input)}
            />
          </div>
          <Button onClick={() => handleSend(input)} disabled={!input.trim()} loading={isTyping}>
            <Send size={16} />
            Send
          </Button>
        </div>
      </GlassCard>
    </motion.div>
  )
}
