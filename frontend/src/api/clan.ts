import { solicitar } from './cliente'

/** Refleja a mano el esquema ClanOut del backend. */
export interface Clan {
  tag: string
  nombre: string
  nivel: number
  miembros: number
  puntos_clan: number | null
  guerras_ganadas: number | null
  racha_victorias: number | null
  trofeos_requeridos: number | null
  descripcion: string | null
}

export function obtenerClan(): Promise<Clan> {
  return solicitar<Clan>('/api/clan')
}