import { solicitar } from './cliente'

export interface AtaqueGuerra {
  orden: number
  atacante_tag: string
  atacante_nombre: string | null
  defensor_tag: string
  defensor_nombre: string | null
  estrellas: number
  destruccion: number
  duracion_segundos: number | null
}

export interface MiembroGuerra {
  tag: string
  nombre: string
  nivel_ayuntamiento: number
  posicion_mapa: number
  ataques_realizados: AtaqueGuerra[]
  ataques_recibidos: number
  mejor_ataque_recibido: AtaqueGuerra | null
}

export interface BandoGuerra {
  tag: string
  nombre: string
  nivel_clan: number
  estrellas: number
  destruccion: number
  ataques_usados: number | null
  experiencia_ganada: number | null
  miembros: MiembroGuerra[]
}

export interface GuerraActual {
  estado: string
  tamano_equipo: number | null
  ataques_por_miembro: number | null
  modificador_batalla: string | null
  preparacion_inicio: string | null
  inicio: string | null
  fin: string | null
  clan: BandoGuerra | null
  rival: BandoGuerra | null
}

export function obtenerGuerraActual(): Promise<GuerraActual> {
  return solicitar<GuerraActual>('/api/guerras/actual')
}

/** Dispara un sondeo manual: consulta la guerra actual y la guarda en el historial. */
export function sondearGuerraActual(): Promise<unknown> {
  return solicitar('/api/guerras/actual', { method: 'POST' })
}

/** Resumen de una guerra guardada, sin el detalle de miembros ni ataques. */
export interface GuerraResumen {
  id: number
  estado: string
  war_tag: string | null
  liga_temporada: string | null
  liga_ronda: number | null
  tamano_equipo: number | null
  ataques_por_miembro: number | null
  clan_nivel: number
  clan_estrellas: number
  clan_destruccion: number
  clan_ataques_usados: number | null
  rival_nombre: string
  rival_nivel: number
  rival_estrellas: number
  rival_destruccion: number
  inicio: string | null
  fin: string | null
  ultima_actualizacion_en: string
}

export function listarHistorialGuerras(limite = 10): Promise<GuerraResumen[]> {
  return solicitar<GuerraResumen[]>(`/api/guerras/historial?limite=${limite}`)
}