import { describe, expect, it } from 'vitest'
import { expandBoardFocusCapacity } from '../src/components/agent-board/boardLayout'

describe('expandBoardFocusCapacity', () => {
  const base = {
    canvasWidth: 1400,
    canvasHeight: 900,
    canvasPaddingLeft: 0,
    canvasPaddingTop: 0,
    scale: 1,
  }

  it('adds leading canvas space when centering would require negative scrolling', () => {
    expect(
      expandBoardFocusCapacity({
        ...base,
        targetLeft: -320,
        targetTop: -120,
        maxScrollLeft: 400,
        maxScrollTop: 300,
      }),
    ).toEqual({
      canvasWidth: 1400,
      canvasHeight: 900,
      canvasPaddingLeft: 320,
      canvasPaddingTop: 120,
      expanded: true,
    })
  })

  it('extends the trailing canvas when the centered target exceeds the scroll range', () => {
    expect(
      expandBoardFocusCapacity({
        ...base,
        targetLeft: 640,
        targetTop: 450,
        maxScrollLeft: 400,
        maxScrollTop: 300,
        scale: 2,
      }),
    ).toEqual({
      canvasWidth: 1520,
      canvasHeight: 975,
      canvasPaddingLeft: 0,
      canvasPaddingTop: 0,
      expanded: true,
    })
  })

  it('keeps the canvas unchanged when the node can already be centered', () => {
    expect(
      expandBoardFocusCapacity({
        ...base,
        targetLeft: 200,
        targetTop: 150,
        maxScrollLeft: 400,
        maxScrollTop: 300,
      }),
    ).toEqual({
      canvasWidth: 1400,
      canvasHeight: 900,
      canvasPaddingLeft: 0,
      canvasPaddingTop: 0,
      expanded: false,
    })
  })
})
