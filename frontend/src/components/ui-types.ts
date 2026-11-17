export type ChipTone = 'neutral' | 'accent' | 'ok' | 'warn' | 'danger' | 'info'

export interface StageStep {
  stage: string
  at?: string | null
}

export interface DonutSegment {
  label: string
  value: number
  tone?: string
}

export interface TableColumn {
  key: string
  label: string
  width?: number | string
  minWidth?: number | string
  align?: 'left' | 'center' | 'right'
  hideOnMobile?: boolean
  /** 作为移动卡片的标题字段 */
  primary?: boolean
}
