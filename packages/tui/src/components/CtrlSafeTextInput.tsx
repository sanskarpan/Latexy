import React, { useEffect, useState } from 'react'
import { Text, useInput } from 'ink'

/*
 * This is a small, intentionally local adaptation of ink-text-input 6.0.0.
 * The package is MIT-licensed:
 *
 * Copyright (c) Vadym Demedes <vadimdemedes@hey.com> (github.com/vadimdemedes)
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 *
 * Original source: https://github.com/vadimdemedes/ink-text-input
 */

export interface CtrlSafeTextInputProps {
  readonly placeholder?: string
  readonly focus?: boolean
  readonly mask?: string
  readonly showCursor?: boolean
  readonly highlightPastedText?: boolean
  readonly value: string
  readonly onChange: (value: string) => void
  readonly onSubmit?: (value: string) => void
}

/**
 * Text input with Ctrl-letter handling performed before value/cursor mutation.
 *
 * Ink normalizes control bytes such as Ctrl+L to a one-character `input` with
 * `key.ctrl=true`. The regular ink-text-input handler would insert that letter
 * and a later state effect would have to guess where it was inserted. Handling
 * it in the same callback keeps both the controlled value and cursor position
 * unchanged, including when the cursor is in the middle of the text.
 */
export function CtrlSafeTextInput({
  value: originalValue,
  placeholder = '',
  focus = true,
  mask,
  highlightPastedText = false,
  showCursor = true,
  onChange,
  onSubmit,
}: CtrlSafeTextInputProps): React.ReactElement {
  const [state, setState] = useState({
    cursorOffset: (originalValue || '').length,
    cursorWidth: 0,
  })
  const { cursorOffset, cursorWidth } = state

  useEffect(() => {
    setState(previousState => {
      if (!focus || !showCursor) return previousState
      const nextValue = originalValue || ''
      if (previousState.cursorOffset > nextValue.length - 1) {
        return { cursorOffset: nextValue.length, cursorWidth: 0 }
      }
      return previousState
    })
  }, [originalValue, focus, showCursor])

  useInput((input, key) => {
    // Ctrl+C is handled by Ink/AppShell and ink-text-input never inserts it.
    // Other normalized one-character control inputs must not reach the generic
    // insertion branch below. This is deliberately before cursor mutation.
    if (key.ctrl && input.length === 1) return
    if (
      key.upArrow ||
      key.downArrow ||
      key.tab ||
      (key.shift && key.tab)
    ) {
      return
    }
    if (key.return) {
      onSubmit?.(originalValue)
      return
    }

    let nextCursorOffset = cursorOffset
    let nextValue = originalValue
    let nextCursorWidth = 0
    if (key.leftArrow) {
      if (showCursor) nextCursorOffset--
    } else if (key.rightArrow) {
      if (showCursor) nextCursorOffset++
    } else if (key.backspace || key.delete) {
      if (cursorOffset > 0) {
        nextValue = originalValue.slice(0, cursorOffset - 1)
          + originalValue.slice(cursorOffset)
        nextCursorOffset--
      }
    } else {
      // Ink only normalizes isolated control keys. Coalesced input/pastes
      // can still contain raw C0 bytes; retain the same paste whitespace as
      // PromptInput, but never insert terminal control bytes into a field.
      const text = input.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
      nextValue = originalValue.slice(0, cursorOffset)
        + text
        + originalValue.slice(cursorOffset)
      nextCursorOffset += text.length
      if (text.length > 1) nextCursorWidth = text.length
    }

    // Clamp the newly calculated position, not the previous position. This
    // preserves the cursor after an insertion and prevents repeated Left or
    // Backspace keys from creating an invalid offset.
    nextCursorOffset = Math.max(0, Math.min(nextCursorOffset, nextValue.length))
    setState({ cursorOffset: nextCursorOffset, cursorWidth: nextCursorWidth })
    if (nextValue !== originalValue) onChange(nextValue)
  }, { isActive: focus })

  const cursorVisible = focus && showCursor
  const cursorActualWidth = cursorVisible && highlightPastedText ? cursorWidth : 0
  const displayValue = mask ? mask.repeat(originalValue.length) : originalValue
  type Segment = { text: string; inverse?: boolean }
  const segments: Segment[] = []
  const append = (text: string, inverse = false): void => {
    if (text.length === 0) return
    const previous = segments.at(-1)
    if (previous?.inverse === inverse) {
      previous.text += text
      return
    }
    segments.push({ text, inverse })
  }

  if (displayValue.length === 0) {
    if (cursorVisible && placeholder.length === 0) {
      append(' ', true)
    } else if (placeholder.length > 0) {
      if (cursorVisible) append(placeholder[0]!, true)
      append(cursorVisible ? placeholder.slice(1) : placeholder)
    }
  } else {
    for (const [index, char] of [...displayValue].entries()) {
      const selected = cursorVisible
        && index >= cursorOffset - cursorActualWidth
        && index <= cursorOffset
      append(char, selected)
    }
    if (cursorVisible && cursorOffset === displayValue.length) {
      append(' ', true)
    }
  }

  return (
    <Text>
      {segments.map((segment, index) => (
        segment.inverse
          ? <Text inverse key={index}>{segment.text}</Text>
          : <Text color={displayValue.length === 0 ? 'gray' : undefined} key={index}>{segment.text}</Text>
      ))}
    </Text>
  )
}
