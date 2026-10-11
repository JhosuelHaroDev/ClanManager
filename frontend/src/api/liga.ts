import type { GuerraResumen } from './guerras'
import { solicitar } from './cliente'

/** Qué pasó con un miembro en una ronda concreta de la liga. */
export type EstadoAtaque = 'ataco' | 'pendiente' | 'sin_ataque' | 'no_alineado'

export interface RondaMiembro {
  ronda: number
  estado: EstadoAtaque
  estrellas: number | null
  destruccion: number | null
}

export interface MiembroLiga {
  tag: string
  nombre: string
  nivel_ayuntamiento: number
  rondas_alineado: number
  ataques_realizados: number
  ataques_perdidos: number
  estrellas_total: number
  destruccion_promedio: number | null
  rondas: RondaMiembro[]
}

export interface ResumenLiga {
  temporada: string | null
  rondas: GuerraResumen[]
  miembros: MiembroLiga[]
}

export function obtenerResumenLiga(): Promise<ResumenLiga> {
  return solicitar<ResumenLiga>('/api/liga/resumen')
}

/** Dispara un sondeo manual de la liga: trae de Supercell las rondas disponibles y las guarda. */
export function sondearLiga(): Promise<{ en_liga: boolean; rondas_guardadas: number }> {
  return solicitar('/api/liga/sondeo', { method: 'POST' })
}