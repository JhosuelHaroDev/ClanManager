import { solicitar } from './cliente'

/**
 * Forma de un miembro dentro de una captura guardada: igual que Miembro
 * en api/miembros.ts, pero con los niveles de héroe incluidos, porque
 * esos solo se guardan al crear una captura, no en la lista en vivo.
 */
export interface MiembroCapturado {
  tag: string
  nombre: string
  rol: string
  nivel_experiencia: number
  nivel_ayuntamiento: number
  trofeos: number
  donaciones: number
  donaciones_recibidas: number
  liga: string | null
  rango_clan: number | null
  rango_clan_anterior: number | null
  trofeos_base: number | null
  liga_base: string | null
  nivel_rey_barbaro: number | null
  nivel_reina_arquera: number | null
  nivel_gran_centinela: number | null
  nivel_principe_esbirro: number | null
  nivel_luchadora_real: number | null
  nivel_duque_dragon: number | null
}

export interface CapturaDetalle {
  id: number
  capturado_en: string
  nombre_clan: string
  nivel_clan: number
  total_miembros: number
  miembros: MiembroCapturado[]
}

export function obtenerUltimaCaptura(): Promise<CapturaDetalle> {
  return solicitar<CapturaDetalle>('/api/capturas/ultima')
}

/** Dispara una captura manual: consulta el clan en vivo, con los héroes de cada miembro, y la guarda. */
export function dispararCaptura(): Promise<unknown> {
  return solicitar('/api/capturas', { method: 'POST' })
}