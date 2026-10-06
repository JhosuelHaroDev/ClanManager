import { useEffect, useState } from 'react'
import {
  listarHistorialGuerras,
  obtenerGuerraActual,
  sondearGuerraActual,
  type GuerraActual,
  type GuerraResumen,
  type MiembroGuerra,
} from '../api/guerras'
import { ErrorApi } from '../api/cliente'
import { BotonRefresco } from '../componentes/BotonRefresco'

const ETIQUETA_ESTADO: Record<string, string> = {
  notInWar: 'Sin guerra activa',
  preparation: 'Preparación',
  inWar: 'En guerra',
  warEnded: 'Terminada',
}

function estrellasDe(miembro: MiembroGuerra): number {
  return miembro.ataques_realizados.reduce((total, ataque) => total + ataque.estrellas, 0)
}

function mejorDestruccionDe(miembro: MiembroGuerra): number {
  return miembro.ataques_realizados.reduce((max, ataque) => Math.max(max, ataque.destruccion), 0)
}

function formatearFecha(fecha: string | null): string {
  if (!fecha) return '—'
  return new Date(fecha).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })
}

/** Dos decimales fijos para los porcentajes de destrucción, que la API entrega con muchos más. */
function formatearPorcentaje(valor: number): string {
  return `${valor.toFixed(2)}%`
}

type Resultado = 'victoria' | 'derrota' | 'empate' | 'en_curso'

const ETIQUETA_RESULTADO: Record<Resultado, string> = {
  victoria: 'Victoria',
  derrota: 'Derrota',
  empate: 'Empate',
  en_curso: 'En curso',
}

const COLOR_RESULTADO: Record<Resultado, string> = {
  victoria: '#16A34A',
  derrota: '#DC2626',
  empate: '#6B7280',
  en_curso: '#2B7FAE',
}

/**
 * Resultado de una guerra guardada, siguiendo el mismo criterio de
 * desempate que usa el juego: primero estrellas, y si están empatadas,
 * el porcentaje de destrucción. Antes de que la guerra termine, el
 * resultado todavía no es definitivo, así que se marca aparte.
 */
function resultadoDe(g: GuerraResumen): Resultado {
  if (g.estado !== 'warEnded') return 'en_curso'
  if (g.clan_estrellas !== g.rival_estrellas) {
    return g.clan_estrellas > g.rival_estrellas ? 'victoria' : 'derrota'
  }
  if (g.clan_destruccion !== g.rival_destruccion) {
    return g.clan_destruccion > g.rival_destruccion ? 'victoria' : 'derrota'
  }
  return 'empate'
}

export function PaginaGuerra() {
  const [guerra, setGuerra] = useState<GuerraActual | null>(null)
  const [historial, setHistorial] = useState<GuerraResumen[]>([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function cargar() {
    setCargando(true)
    setError(null)
    try {
      const [guerraCargada, historialCargado] = await Promise.all([
        obtenerGuerraActual(),
        listarHistorialGuerras(10),
      ])
      setGuerra(guerraCargada)
      setHistorial(historialCargado)
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : 'No se pudo conectar con el servidor')
    } finally {
      setCargando(false)
    }
  }

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    cargar()
  }, [])

  async function actualizar() {
    await sondearGuerraActual()
    await cargar()
  }

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-display text-xl font-bold text-guerra-texto">Guerra clásica</h2>
        <BotonRefresco
          seccion="guerra"
          alActualizar={actualizar}
          className="border-guerra-borde bg-guerra-panel text-guerra-texto hover:brightness-95"
        />
      </div>

      {error && (
        <p className="rounded-lg border-2 border-red-300 bg-red-50 px-4 py-2 text-red-700">{error}</p>
      )}
      {cargando && <p>Cargando…</p>}

      {!cargando && !error && guerra && (
        <div className="rounded-2xl border-4 border-guerra-borde bg-guerra-fondo p-6 text-guerra-texto">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <span className="rounded-full border-2 border-guerra-borde bg-guerra-panel px-3 py-1 font-display font-semibold">
              {ETIQUETA_ESTADO[guerra.estado] ?? guerra.estado}
            </span>
            {guerra.tamano_equipo && <span>Equipos de {guerra.tamano_equipo}</span>}
            {guerra.fin && <span>Termina: {formatearFecha(guerra.fin)}</span>}
          </div>

          {!guerra.clan || !guerra.rival ? (
            <p>Tu clan no está en guerra en este momento.</p>
          ) : (
            <>
              <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
                <ResumenBando titulo="Tu clan" bando={guerra.clan} />
                <ResumenBando titulo="Rival" bando={guerra.rival} alineacionDerecha />
              </div>

              <div className="overflow-x-auto rounded-xl border-2 border-guerra-borde bg-guerra-panel">
                <table className="w-full text-left">
                  <thead className="font-display">
                    <tr className="border-b-2 border-guerra-borde">
                      <th className="px-3 py-2">Pos.</th>
                      <th className="px-3 py-2">Nombre</th>
                      <th className="px-3 py-2">Ayunt.</th>
                      <th className="px-3 py-2">Ataques</th>
                      <th className="px-3 py-2">⭐ obtenidas</th>
                      <th className="px-3 py-2">Mejor destrucción</th>
                      <th className="px-3 py-2">Mejor ataque recibido</th>
                    </tr>
                  </thead>
                  <tbody>
                    {guerra.clan.miembros.map((miembro) => (
                      <tr
                        key={miembro.tag}
                        className="border-t border-guerra-borde/60 transition-colors hover:bg-guerra-fondo/60"
                      >
                        <td className="px-3 py-2">{miembro.posicion_mapa}</td>
                        <td className="px-3 py-2 font-semibold">{miembro.nombre}</td>
                        <td className="px-3 py-2">{miembro.nivel_ayuntamiento}</td>
                        <td className="px-3 py-2">
                          {miembro.ataques_realizados.length}
                          {guerra.ataques_por_miembro ? ` / ${guerra.ataques_por_miembro}` : ''}
                        </td>
                        <td className="px-3 py-2 font-semibold text-guerra-acento">
                          {'⭐'.repeat(estrellasDe(miembro)) || '—'}
                        </td>
                        <td className="px-3 py-2">
                          {miembro.ataques_realizados.length ? formatearPorcentaje(mejorDestruccionDe(miembro)) : '—'}
                        </td>
                        <td className="px-3 py-2">
                          {miembro.mejor_ataque_recibido
                            ? `${miembro.mejor_ataque_recibido.atacante_nombre ?? miembro.mejor_ataque_recibido.atacante_tag} · ${miembro.mejor_ataque_recibido.estrellas}⭐ (${formatearPorcentaje(miembro.mejor_ataque_recibido.destruccion)})`
                            : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {!cargando && !error && (
        <div>
          <h3 className="mb-2 font-display text-lg font-bold text-guerra-texto">Guerras clásicas anteriores</h3>
          <div className="overflow-x-auto rounded-xl border-2 border-guerra-borde bg-guerra-panel">
            <table className="w-full text-left">
              <thead className="font-display">
                <tr className="border-b-2 border-guerra-borde">
                  <th className="px-3 py-2">Resultado</th>
                  <th className="px-3 py-2">Rival</th>
                  <th className="px-3 py-2">Nivel rival</th>
                  <th className="px-3 py-2">Marcador</th>
                  <th className="px-3 py-2">Equipos</th>
                  <th className="px-3 py-2">Ataques usados</th>
                  <th className="px-3 py-2">Inicio</th>
                  <th className="px-3 py-2">Terminó</th>
                </tr>
              </thead>
              <tbody>
                {historial.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-3 py-3 text-center text-guerra-texto/60">
                      Todavía no hay guerras clásicas guardadas.
                    </td>
                  </tr>
                )}
                {historial.map((g) => {
                  const resultado = resultadoDe(g)
                  return (
                    <tr key={g.id} className="border-t border-guerra-borde/60 transition-colors hover:bg-guerra-fondo/60">
                      <td className="px-3 py-2 font-display font-bold" style={{ color: COLOR_RESULTADO[resultado] }}>
                        {ETIQUETA_RESULTADO[resultado].toUpperCase()}
                      </td>
                      <td className="px-3 py-2 font-semibold">{g.rival_nombre}</td>
                      <td className="px-3 py-2">{g.rival_nivel}</td>
                      <td className="px-3 py-2">
                        {g.clan_estrellas}⭐ ({formatearPorcentaje(g.clan_destruccion)}) — {g.rival_estrellas}⭐ (
                        {formatearPorcentaje(g.rival_destruccion)})
                      </td>
                      <td className="px-3 py-2">{g.tamano_equipo ? `${g.tamano_equipo} vs ${g.tamano_equipo}` : '—'}</td>
                      <td className="px-3 py-2">
                        {g.clan_ataques_usados ?? '—'}
                        {g.clan_ataques_usados !== null && g.tamano_equipo && g.ataques_por_miembro
                          ? ` / ${g.tamano_equipo * g.ataques_por_miembro}`
                          : ''}
                      </td>
                      <td className="px-3 py-2">{formatearFecha(g.inicio)}</td>
                      <td className="px-3 py-2">{formatearFecha(g.fin)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}

function ResumenBando({
  titulo,
  bando,
  alineacionDerecha = false,
}: {
  titulo: string
  bando: { nombre: string; nivel_clan: number; estrellas: number; destruccion: number; ataques_usados: number | null }
  alineacionDerecha?: boolean
}) {
  return (
    <div
      className={`rounded-xl border-2 border-guerra-borde bg-guerra-panel p-4 ${alineacionDerecha ? 'text-right' : ''}`}
    >
      <p className="font-display text-sm uppercase tracking-wide text-guerra-texto/60">{titulo}</p>
      <p className="font-display text-lg font-bold">
        {bando.nombre} <span className="text-sm font-normal">(nivel {bando.nivel_clan})</span>
      </p>
      <p className="text-guerra-acento">
        {bando.estrellas}⭐ · {formatearPorcentaje(bando.destruccion)} de destrucción
      </p>
      {bando.ataques_usados !== null && <p className="text-sm">{bando.ataques_usados} ataques usados</p>}
    </div>
  )
}