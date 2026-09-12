/**
 * 大纲草稿（P1-A3 的增、删、改名、调序）。
 *
 * 屏幕上这棵树与库里那棵**不是同一棵**：删页、加页、加章、拖动都只动本地这份
 * 草稿，点「确认大纲」时才整棵发回去（`POST /courses/{id}/outline`），由服务端
 * 重排页号与状态。所以这里不校验、也不算页号 —— 页号是服务端的活，
 * 本地只管把「用户想要什么」表达清楚。
 *
 * 新增的页带着**负数页号**：提交时页号根本不发（服务端按顺序重排），负数只是
 * 让本地的 `:key` 不重复，也不会撞上 `selectedNo` / `livePageNo`（真页号从 1 起）。
 *
 * 开篇与收尾（封面、大纲页、小结）不在这里 —— 它们由管线按规则补齐，不在
 * `chapters` 里，改了就丢，所以界面上也不给它们任何编辑入口。
 */
import { ref, type Ref } from 'vue'

import type { OutlineChapter, OutlinePageItem, OutlineSubmit, OutlineTree } from '@/types/api'

/** 新增页还没定名时的名字。服务端会照抄它，所以得是句人话而不是空串。 */
const UNTITLED = '新页面'

export function useOutlineDraft(tree: Ref<OutlineTree | null>) {
  /** 临时页号的发号器：从 -1 往下发，同一棵树里不会重复。 */
  const seq = ref(0)
  /** 有本地改动还没提交。界面上要说一声，重问大纲时也别把它冲掉。 */
  const dirty = ref(false)

  function newPage(title: string): OutlinePageItem {
    seq.value -= 1
    return {
      pageNo: seq.value,
      kind: 'concept',
      title: title.trim() || UNTITLED,
      status: 'pending',
      rev: 0,
    }
  }

  /** 只换掉一章，其余章节原样带过去 —— 免得整棵树重建、选中态与滚动全丢。 */
  function mapChapter(no: number, mapper: (chapter: OutlineChapter) => OutlineChapter): void {
    const current = tree.value
    if (!current) return
    tree.value = {
      ...current,
      chapters: current.chapters.map((chapter) =>
        chapter.no === no ? mapper(chapter) : chapter,
      ),
    }
  }

  /** 删一页。页被删光的章节留在树上（提交时才丢），这样还能往里加回来。 */
  function removePage(payload: { chapterNo: number; pageNo: number }): void {
    mapChapter(payload.chapterNo, (chapter) => ({
      ...chapter,
      pages: chapter.pages.filter((item) => item.pageNo !== payload.pageNo),
    }))
    dirty.value = true
  }

  /** 给某一章加一页，返回新页 —— 调用方拿它的页号去打开改名框。 */
  function addPage(chapterNo: number, title = ''): OutlinePageItem | null {
    const current = tree.value
    if (!current) return null
    const page = newPage(title)
    mapChapter(chapterNo, (chapter) => ({ ...chapter, pages: [...chapter.pages, page] }))
    dirty.value = true
    return page
  }

  /**
   * 加一章。**自带一页**：一章没有正文页，服务端会整章丢掉
   * （`parse_outline`），加了等于没加。
   */
  function addChapter(title = '', pageTitle = ''): OutlineChapter | null {
    const current = tree.value
    if (!current) return null
    const no = current.chapters.reduce((max, chapter) => Math.max(max, chapter.no), 0) + 1
    const chapter: OutlineChapter = {
      no,
      title: title.trim() || `第 ${no} 章 · 新章节`,
      summary: '',
      points: [],
      discussion: [],
      pages: [newPage(pageTitle)],
    }
    tree.value = { ...current, chapters: [...current.chapters, chapter] }
    dirty.value = true
    return chapter
  }

  function renameChapter(payload: { chapterNo: number; title: string }): void {
    const title = payload.title.trim()
    if (!title) return
    mapChapter(payload.chapterNo, (chapter) => ({ ...chapter, title }))
    dirty.value = true
  }

  function renamePage(payload: { chapterNo: number; pageNo: number; title: string }): void {
    const title = payload.title.trim() || UNTITLED
    mapChapter(payload.chapterNo, (chapter) => ({
      ...chapter,
      pages: chapter.pages.map((item) => (item.pageNo === payload.pageNo ? { ...item, title } : item)),
    }))
    dirty.value = true
  }

  /**
   * 把一页拖到另一页的位置。
   *
   * 拖的是「这一页换个位置」，跨章也一样：先在**整棵树的正文页**这条平坦序列上
   * 搬，再按它落到哪一章分回各章。往下拖插到目标页后面、往上拖插到前面 ——
   * 就是所有列表拖动的那条直觉（`splice(from)` 之后目标的位置自己会挪一格）。
   */
  function movePage(payload: { pageNo: number; overPageNo: number }): void {
    const current = tree.value
    if (!current || payload.pageNo === payload.overPageNo) return

    const flat = current.chapters.flatMap((chapter) =>
      chapter.pages.map((item) => ({ chapterNo: chapter.no, item })),
    )
    const from = flat.findIndex((row) => row.item.pageNo === payload.pageNo)
    const to = flat.findIndex((row) => row.item.pageNo === payload.overPageNo)
    if (from < 0 || to < 0) return

    const [moved] = flat.splice(from, 1)
    flat.splice(to, 0, moved)

    // 被拖的这页跟着落点走：落在哪一章的页上，它就是哪一章的
    const owner = new Map(flat.map((row) => [row.item.pageNo, row.chapterNo]))
    owner.set(moved.item.pageNo, owner.get(payload.overPageNo) ?? moved.chapterNo)

    tree.value = {
      ...current,
      chapters: current.chapters.map((chapter) => ({
        ...chapter,
        pages: flat
          .filter((row) => owner.get(row.item.pageNo) === chapter.no)
          .map((row) => row.item),
      })),
    }
    dirty.value = true
  }

  /**
   * 提交的 body。页号、状态、页数一概不算 —— 服务端会重排（`intake.clean_outline`）。
   * 页被删光的章节不交：交上去也会被拒。
   */
  function toSubmit(): OutlineSubmit | null {
    const current = tree.value
    if (!current) return null
    return {
      title: current.title,
      chapters: current.chapters
        .filter((chapter) => chapter.pages.length > 0)
        .map((chapter) => ({
          no: chapter.no,
          title: chapter.title,
          summary: chapter.summary,
          points: chapter.points,
          discussion: chapter.discussion,
          pages: chapter.pages.map((item) => ({ kind: item.kind, title: item.title })),
        })),
    }
  }

  /** 提交成功 / 换了一门课：本地没有未提交的改动了。 */
  function markClean(): void {
    dirty.value = false
  }

  return {
    dirty,
    addChapter,
    addPage,
    markClean,
    movePage,
    removePage,
    renameChapter,
    renamePage,
    toSubmit,
  }
}
