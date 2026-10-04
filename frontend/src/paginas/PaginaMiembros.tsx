import { useEffect, useState } from 'react'
import { dispararCaptura, obtenerUltimaCaptura, type CapturaDetalle, type MiembroCapturado } from '../api/capturas'
import { obtenerClan, type Clan } from '../api/clan'
import { ErrorApi } from '../api/cliente'
import { BotonRefresco } from '../componentes/BotonRefresco'
import { colorLiga } from '../utilidades/colorLiga'
import { type ClaveHeroe, colorNivelHeroe } from '../utilidades/heroes'

/** Una columna de héroe: su clave en el diccionario de niveles y la abreviatura a mostrar. */
const COLUMNAS_HEROE: { clave: ClaveHeroe; etiqueta: string; campo: keyof MiembroCapturado }[] = [
  { clave: 'bk', etiqueta: 'RB', campo: 'nivel_rey_barbaro' },
  { clave: 'aq', etiqueta: 'RA', campo: 'nivel_reina_arquera' },
  { clave: 'gw', etiqueta: 'GC', campo: 'nivel_gran_centinela' },
  { clave: 'mp', etiqueta: 'PE', campo: 'nivel_principe_esbirro' },
  { clave: 'rc', etiqueta: 'LR', campo: 'nivel_luchadora_real' },
  { clave: 'dd', etiqueta: 'DD', campo: 'nivel_duque_dragon' },
]

export function PaginaMiembros() {
  const [clan, setClan] = useState<Clan | null>(null)
  const [captura, setCaptura] = useState<CapturaDetalle | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function cargar() {
    setCargando(true)
    setError(null)
    try {
      const [clanCargado, capturaCargada] = await Promise.all([obtenerClan(), obtenerUltimaCaptura()])
      setClan(clanCargado)
      setCaptura(capturaCargada)
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
    await dispararCaptura()
    await cargar()
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-display text-xl font-bold">
          Miembros del clan
          {clan && (
            <span className="font-normal text-base-texto/70">
              {' — '}
              {clan.nombre} · Nivel {clan.nivel} · ({clan.tag}) · {clan.miembros} miembros
              {clan.puntos_clan !== null && <> · 🏆 {clan.puntos_clan.toLocaleString()} puntos</>}
              {clan.guerras_ganadas !== null && <> · ⚔️ {clan.guerras_ganadas} guerras ganadas</>}
              {clan.racha_victorias !== null && <> · 🔥 racha de {clan.racha_victorias}</>}
            </span>
          )}
        </h2>
        <BotonRefresco seccion="miembros" alActualizar={actualizar} />
      </div>

      {error && (
        <p className="rounded-lg border-2 border-red-300 bg-red-50 px-4 py-2 text-red-700">{error}</p>
      )}

      {cargando && <p>Cargando…</p>}

      {!cargando && !error && captura && (
        <div className="overflow-x-auto rounded-xl border-2 border-base-borde bg-base-panel">
          <table className="w-full text-left">
            <thead className="bg-base-fondo font-display">
              <tr>
                <th className="px-3 py-2">N°</th>
                <th className="px-3 py-2">Tag</th>
                <th className="px-3 py-2">Nombre</th>
                <th className="px-3 py-2">Rol</th>
                <th className="px-3 py-2">Ayuntamiento</th>
                <th className="px-3 py-2">Trofeos</th>
                <th className="px-3 py-2">Donaciones</th>
                {COLUMNAS_HEROE.map((h) => (
                  <th key={h.clave} className="px-3 py-2" title={h.etiqueta}>
                    {h.etiqueta}
                  </th>
                ))}
                <th className="px-3 py-2">Liga</th>
              </tr>
            </thead>
            <tbody>
              {captura.miembros.map((miembro, indice) => (
                <tr
                  key={miembro.tag}
                  className="border-t border-base-borde transition-colors hover:bg-base-acento/10"
                >
                  <td className="px-3 py-2 text-base-texto/60">{indice + 1}</td>
                  <td className="px-3 py-2 font-mono text-sm text-base-texto/70">{miembro.tag}</td>
                  <td className="px-3 py-2 font-semibold">{miembro.nombre}</td>
                  <td className="px-3 py-2">{miembro.rol}</td>
                  <td className="px-3 py-2">{miembro.nivel_ayuntamiento}</td>
                  <td className="px-3 py-2">{miembro.trofeos}</td>
                  <td className="px-3 py-2">{miembro.donaciones}</td>
                  {COLUMNAS_HEROE.map((h) => {
                    const nivel = miembro[h.campo] as number | null
                    const color = colorNivelHeroe(nivel, miembro.nivel_ayuntamiento, h.clave)
                    return (
                      <td key={h.clave} className="px-3 py-2 text-center font-semibold">
                        {color ? <span style={{ color }}>{nivel}</span> : <span className="text-base-texto/30">—</span>}
                      </td>
                    )
                  })}
                  <td className="px-3 py-2 font-semibold" style={{ color: colorLiga(miembro.liga) }}>
                    {miembro.liga ?? 'Unranked'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}