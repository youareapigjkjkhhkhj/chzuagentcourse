/**
 * 课堂 Store（P3-5 的 F3）。
 *
 * 这一份盯的是**「服务端说什么就是什么」这条纪律有没有被守住**：
 * 事件按 `seq` 去重（补发与广播是两条路，同一条会从任一条到）、
 * 不带 `seq` 的私有帧不参与去重也不许推进游标、消息按 id 去重按时间落位、
 * 一个 turn 只报一次 `beat_done`。
 *
 * 这里**不测界面**：状态对了界面才谈得上对，而这两个错混在一起时，
 * 失败的那条会指向看起来没问题的那一层。
 */

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  clearCursor,
  loadCursor,
  saveCursor,
  useClassroomStore,
} from '@/stores/classroom'
import type {
  BoardStroke,
  ClassroomEvent,
  ClassroomMessage,
  ClassroomQuiz,
  SpeakPayload,
} from '@/types/classroom'

/** 一条带信封的下行事件。`seq` 由这里递增 —— 服务端就是这么发的。 */
let seq = 0
let nextSeq = 0 // 需要「跳号」的用例（补发缺口）自己指定

function event(payload: Record<string, unknown>): ClassroomEvent {
  seq = nextSeq > 0 ? nextSeq : seq + 1
  nextSeq = 0
  return { seq, eventId: `e${seq}`, ts: '2026-09-13T10:00:00', ...payload } as unknown as ClassroomEvent
}

/** 不带 `seq` 的帧（`error` / `ping` 是每连接私有的，见 P3 §4.2）。 */
function raw(payload: Record<string, unknown>): ClassroomEvent {
  return payload as unknown as ClassroomEvent
}

function message(patch: Partial<ClassroomMessage> = {}): ClassroomMessage {
  return {
    id: 'm1',
    sessionId: 'cs1',
    speaker: 't1',
    speakerKind: 'teacher',
    type: 'comment',
    text: '这是一条消息',
    pageNo: 1,
    beatId: '',
    audioUrl: '',
    quoteMsgId: '',
    ts: '2026-09-13T10:00:00',
    ...patch,
  }
}

function speak(patch: Partial<SpeakPayload> = {}): SpeakPayload {
  return {
    turnId: 'turn-1',
    speaker: { code: 't1', name: '沈老师' },
    speakerKind: 'teacher',
    text: '我们开始上课。',
    audioUrl: '',
    beats: ['b1'],
    kind: 'lecture',
    priority: 10,
    pageNo: 1,
    ...patch,
  }
}

function stroke(pageNo: number, no: number): BoardStroke {
  return {
    id: `s${no}`,
    sessionId: 'cs1',
    pageNo,
    strokeNo: no,
    tool: 'polyline',
    color: '#0052d9',
    width: 3,
    points: [
      { x: 0.1, y: 0.1 },
      { x: 0.4, y: 0.4 },
    ],
    text: '',
    atBeatId: '',
    durMs: 800,
    author: 'teacher',
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  seq = 0
  nextSeq = 0
  window.sessionStorage.clear()
})

describe('事件流：按 seq 去重，游标只由带 seq 的帧推进', () => {
  it('同一个 seq 再来一次不吃：补发与广播是两条路，同一条会从任一条到', () => {
    const store = useClassroomStore()
    const first = event({ type: 'subtitle', beatId: 'b1', text: '第一句', pageNo: 1 })

    expect(store.applyEvent(first)).toBe(true)
    expect(store.applyEvent({ ...first })).toBe(false) // 重发（或 HTTP 回执 + WS 广播）同一条
    expect(store.subtitles).toHaveLength(1)
    expect(store.lastSeq).toBe(1)
  })

  it('迟到的旧 seq 不吃：补发回来的那几条晚到，不能把位置往回改', () => {
    const store = useClassroomStore()
    store.applyEvent(event({ type: 'state', status: 'lecture', pageNo: 1, beatIdx: 0, elapsedMs: 0, totalMs: 1000, speed: 1 }))
    store.applyEvent(event({ type: 'state', status: 'lecture', pageNo: 3, beatIdx: 2, elapsedMs: 500, totalMs: 1000, speed: 1 }))

    const stale = { seq: 1, eventId: 'e1', ts: '', type: 'state', status: 'lecture', pageNo: 1, beatIdx: 0, elapsedMs: 0, totalMs: 1000, speed: 1 }
    expect(store.applyEvent(stale as unknown as ClassroomEvent)).toBe(false)
    expect(store.pageNo).toBe(3)
    expect(store.beatIdx).toBe(2)
  })

  it('私有帧（error）不带 seq：不参与去重，也不把游标带偏', () => {
    const store = useClassroomStore()
    store.applyEvent(event({ type: 'subtitle', beatId: 'b1', text: '第一句', pageNo: 1 }))

    expect(store.applyEvent(raw({ type: 'error', code: 'too_fast', message: '说慢一点' }))).toBe(true)
    expect(store.lastSeq).toBe(1) // 游标没动
    expect(store.lastError).toBe('说慢一点')
  })

  it('未知类型静默忽略：新服务端多发一种事件不该把旧页面弄崩', () => {
    const store = useClassroomStore()
    expect(store.applyEvent(event({ type: 'hologram', text: '未来才有的事件' }))).toBe(true)
    expect(store.lastSeq).toBe(1)
  })
})

describe('发言与字幕', () => {
  it('speak_end 抄下刚结束那一轮的 kind —— 它自己不带这个字段', () => {
    const store = useClassroomStore()
    store.applyEvent(event({ type: 'speak', ...speak({ turnId: 't-1', kind: 'answer' }) }))
    store.applyEvent(event({ type: 'speak_end', turnId: 't-1' }))

    expect(store.speakEnd?.kind).toBe('answer')
    expect(store.speakEnd?.preempted).toBe(false)
    expect(store.speaking).toBeNull()
  })

  it('被打断的那一轮也记下来，但标着 preempted —— 时间线不为它动', () => {
    const store = useClassroomStore()
    store.applyEvent(event({ type: 'speak', ...speak({ turnId: 't-2' }) }))
    store.applyEvent(event({ type: 'speak_end', turnId: 't-2', preempted: true }))

    expect(store.speakEnd).toMatchObject({ turnId: 't-2', preempted: true, kind: 'lecture' })
  })

  it('迟到的 speak_end（不是当前这一轮）不动正在说的那一条', () => {
    const store = useClassroomStore()
    store.applyEvent(event({ type: 'speak', ...speak({ turnId: 't-3' }) }))
    store.applyEvent(event({ type: 'speak_end', turnId: 't-9' }))

    expect(store.speakEnd?.kind).toBe('') // 认不出刚结束的是什么
    expect(store.speaking?.turnId).toBe('t-3')
  })

  it('字幕按 beatId 去重：同一个 beat 被重讲一次不该在列表里出现两行', () => {
    const store = useClassroomStore()
    store.applyEvent(event({ type: 'subtitle', beatId: 'b1', text: '第一句', pageNo: 1 }))
    store.applyEvent(event({ type: 'subtitle', beatId: 'b1', text: '第一句', pageNo: 1 }))
    store.applyEvent(event({ type: 'subtitle', beatId: 'b2', text: '第二句', pageNo: 1 }))

    expect(store.subtitles.map((item) => item.beatId)).toEqual(['b1', 'b2'])
    expect(store.currentSubtitle?.text).toBe('第二句')
  })

  it('消息带 beatId 时同时是一条字幕（同一张表的同一行）', () => {
    const store = useClassroomStore()
    store.applyEvent(event({ type: 'message', msg: message({ beatId: 'b7', text: '这一句是讲稿' }) }))

    expect(store.subtitles.map((item) => item.beatId)).toEqual(['b7'])
  })
})

describe('消息：按 id 去重、按时间落位', () => {
  it('补发回来的那条晚到，也要排回它该在的位置', () => {
    const store = useClassroomStore()
    store.applyEvent(event({ type: 'message', msg: message({ id: 'm1', ts: '2026-09-13T10:00:00', text: '先说' }) }))
    store.applyEvent(event({ type: 'message', msg: message({ id: 'm3', ts: '2026-09-13T10:00:30', text: '后说' }) }))
    store.applyEvent(event({ type: 'message', msg: message({ id: 'm2', ts: '2026-09-13T10:00:15', text: '中间那句' }) }))

    expect(store.messages.map((item) => item.text)).toEqual(['先说', '中间那句', '后说'])
  })

  it('同一条消息从 HTTP 与 WS 两条路都回来，只留一条', () => {
    const store = useClassroomStore()
    const item = message({ id: 'm1' })
    store.applyEvent(event({ type: 'message', msg: item }))
    store.applyHistory([item])
    store.applyHistory([item, message({ id: 'm2' })])

    expect(store.messages.map((m) => m.id)).toEqual(['m1', 'm2'])
  })

  it('「正在输入…」跟着 speak / message / speak_end 三处收起来', () => {
    const store = useClassroomStore()

    // 静默发言（讨论区不点名老师的发言）只发 message 不发 speak
    store.applyEvent(event({ type: 'typing', speaker: { code: 's1', name: '林晓' }, pageNo: 1 }))
    expect(store.typing?.speaker.name).toBe('林晓')
    store.applyEvent(event({ type: 'message', msg: message({ id: 'm9', speaker: 's1', speakerKind: 'student_ai' }) }))
    expect(store.typing).toBeNull()

    store.applyEvent(event({ type: 'typing', speaker: { code: 't1', name: '沈老师' }, pageNo: 1 }))
    store.applyEvent(event({ type: 'speak', ...speak({ turnId: 't-4' }) }))
    expect(store.typing).toBeNull()

    store.applyEvent(event({ type: 'typing', speaker: { code: 't1', name: '沈老师' }, pageNo: 1 }))
    store.applyEvent(event({ type: 'speak', ...speak({ turnId: 't-5' }) }))
    store.applyEvent(event({ type: 'speak_end', turnId: 't-5' }))
    expect(store.typing).toBeNull()
  })

  it('别人的「正在输入」不该被我的消息清掉', () => {
    const store = useClassroomStore()
    store.applyEvent(event({ type: 'typing', speaker: { code: 't1', name: '沈老师' }, pageNo: 1 }))
    store.applyEvent(event({ type: 'message', msg: message({ id: 'm5', speaker: 's2', speakerKind: 'student_ai' }) }))

    expect(store.typing?.speaker.code).toBe('t1')
  })
})

describe('举手与点名：位次按 ownerId 认「我」', () => {
  it('队列里有我时给位次，被点到名时 iAmCalled 为真', () => {
    const store = useClassroomStore()
    store.ownerId = 'u-me'
    store.applyEvent(
      event({
        type: 'hand_queue',
        queue: [
          { id: 'h1', userId: 'u-other', name: '别人', ts: '', calledAt: '', status: 'waiting' },
          { id: 'h2', userId: 'u-me', name: '我', ts: '', calledAt: '', status: 'waiting' },
        ],
        called: null,
      }),
    )

    expect(store.myHandPosition).toBe(2)
    expect(store.iAmCalled).toBe(false)

    store.applyEvent(
      event({
        type: 'hand_queue',
        queue: [{ id: 'h2', userId: 'u-me', name: '我', ts: '', calledAt: 'x', status: 'called' }],
        called: { id: 'h2', userId: 'u-me', name: '我', ts: '', calledAt: 'x', status: 'called' },
      }),
    )
    expect(store.iAmCalled).toBe(true)
  })

  it('点的是别人时不弹我的提问条', () => {
    const store = useClassroomStore()
    store.ownerId = 'u-me'
    store.applyEvent(
      event({
        type: 'hand_queue',
        queue: [],
        called: { id: 'h1', userId: 'u-other', name: '别人', ts: '', calledAt: 'x', status: 'called' },
      }),
    )

    expect(store.iAmCalled).toBe(false)
  })
})

describe('板书与测验', () => {
  it('板书整页替换；翻旧页补读的也落在同一张表上', () => {
    const store = useClassroomStore()
    store.applyEvent(event({ type: 'board', pageNo: 2, strokes: [stroke(2, 1)] }))
    store.applyEvent(event({ type: 'board', pageNo: 2, strokes: [stroke(2, 1), stroke(2, 2)] }))
    store.applyBoard(7, [stroke(7, 1)])

    expect(store.boards[2]).toHaveLength(2)
    expect(store.boards[7]).toHaveLength(1)
    expect(store.currentStrokes).toHaveLength(0) // 当前页是 0：没有就是空板，不是报错
  })

  it('换题就清掉上一题的判定：否则新题一上来就显示「回答正确」', () => {
    const store = useClassroomStore()
    const quiz: ClassroomQuiz = { pageNo: 3, stem: '感知机的输出是什么？', options: ['A 句', 'B 句'] }
    store.applyEvent(event({ type: 'quiz', ...quiz }))
    store.applyEvent(
      event({ type: 'quiz_result', pageNo: 3, correct: true, option: 'A 句', answer: 'A 句', explain: '', branch: 'pass' }),
    )
    expect(store.quizResult?.correct).toBe(true)

    store.applyEvent(event({ type: 'quiz', ...quiz, pageNo: 5, stem: '下一题' }))
    expect(store.quizResult).toBeNull()
    expect(store.quiz?.pageNo).toBe(5)
  })

  it('课结束时把正在说的那条收起来 —— 下了课还在说话是说不通的', () => {
    const store = useClassroomStore()
    store.applyEvent(event({ type: 'speak', ...speak() }))
    store.applyEvent(event({ type: 'state', status: 'ended', pageNo: 9, beatIdx: 0, elapsedMs: 0, totalMs: 0, speed: 1 }))

    expect(store.speaking).toBeNull()
    expect(store.ended).toBe(true)
    expect(store.live).toBe(false)
  })
})

describe('时间线：一个 turn 只报一次 beat_done', () => {
  it('音频播完与 speak_end 同时到，只认第一条', () => {
    const store = useClassroomStore()
    expect(store.claimBeatReport('t-1')).toBe(true)
    expect(store.claimBeatReport('t-1')).toBe(false)
  })

  it('被打断之后重讲是一轮新的 turnId，仍可再报', () => {
    const store = useClassroomStore()
    expect(store.claimBeatReport('t-1')).toBe(true)
    expect(store.claimBeatReport('t-2')).toBe(true)
  })

  it('空 turnId 不报：没有轮次的东西不该推进时间线', () => {
    const store = useClassroomStore()
    expect(store.claimBeatReport('')).toBe(false)
  })
})

describe('游标：落 sessionStorage，每个标签页一份', () => {
  it('存进去能读回来，清掉就没了', () => {
    saveCursor({ sessionId: 'cs1', seq: 42, courseId: 'c1' })
    expect(loadCursor('c1')).toEqual({ sessionId: 'cs1', seq: 42, courseId: 'c1' })

    clearCursor('c1')
    expect(loadCursor('c1')).toBeNull()
  })

  it('存的值坏了不抛：刷新恢复是锦上添花，不该把正在上的课弄崩', () => {
    window.sessionStorage.setItem('eduagentx.classroom.c1', '{不是 json')
    expect(loadCursor('c1')).toBeNull()
  })

  it('读不到存储时的退路是 null，不是异常', () => {
    const spy = vi.spyOn(window.sessionStorage, 'getItem').mockImplementation(() => {
      throw new Error('隐私模式下不给读')
    })
    expect(loadCursor('c1')).toBeNull()
    spy.mockRestore()
  })
})
