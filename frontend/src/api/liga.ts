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

/** Una guerra de una ronda entre dos clanes cualquiera del grupo. */
export interface Enfrentamiento {
  war_tag: string
  ronda: number
  estado: string
  tamano_equipo: number | null
  inicio: string | null
  fin: string | null
  clan_a_tag: string
  clan_a_nombre: string
  clan_a_nivel: number
  clan_a_estrellas: number
  clan_a_destruccion: number
  clan_b_tag: string
  clan_b_nombre: string
  clan_b_nivel: number
  clan_b_estrellas: number
  clan_b_destruccion: number
  /** Quién ganó, solo cuando la guerra ya terminó. */
  ganador: 'a' | 'b' | 'empate' | null
}

/** Una fila de la clasificación del grupo. */
export interface ClanClasificacion {
  posicion: number
  tag: string
  nombre: string
  nivel: number
  es_propio: boolean
  /** Estrellas totales: las de combate más 10 por cada guerra ganada. */
  estrellas: number
  estrellas_en_combate: number
  estrellas_bono: number
  destruccion: number
  victorias: number
  derrotas: number
  empates: number
}

export interface ResumenLiga {
  temporada: string | null
  ronda_actual: number | null
  total_rondas: number
  clasificacion: ClanClasificacion[]
  enfrentamientos: Enfrentamiento[]
  /** Las guerras de nuestro clan, con su detalle. */
  rondas: GuerraResumen[]
  miembros: MiembroLiga[]
}

export function obtenerResumenLiga(): Promise<ResumenLiga> {
  return solicitar<ResumenLiga>('/api/liga/resumen')
}

/** Dispara un sondeo manual de la liga: trae de Supercell las guerras disponibles de todo el grupo y las guarda. */
export function sondearLiga(): Promise<{ en_liga: boolean; guerras_consultadas: number }> {
  return solicitar('/api/liga/sondeo', { method: 'POST' })
}