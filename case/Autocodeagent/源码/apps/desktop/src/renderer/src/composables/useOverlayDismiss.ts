/**
 * 弹窗遮罩关闭：只有「按下 + 抬起」都落在遮罩自身时才关闭。
 * 直接用 @click.self 会误关 —— 在弹框内拖选文本（如复制 Base URL / API Key）时松手越界到遮罩，
 * 浏览器把 click 的 target 判为按下点与抬起点的最近公共祖先（= 遮罩），于是选完文本弹框就消失、未保存内容丢失。
 */
export function useOverlayDismiss(close: () => void) {
  /** 按下点是否在遮罩自身（弹框内按下时为 false，抬起越界也不关闭） */
  let downOnOverlay = false;

  function onOverlayDown(e: MouseEvent): void {
    downOnOverlay = e.target === e.currentTarget;
  }

  function onOverlayClick(e: MouseEvent): void {
    const dismiss = downOnOverlay && e.target === e.currentTarget;
    downOnOverlay = false;
    if (dismiss) close();
  }

  return { onOverlayDown, onOverlayClick };
}
