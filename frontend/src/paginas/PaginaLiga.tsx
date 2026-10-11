import { useEffect, useState } from 'react'
import { ErrorApi } from '../api/cliente'
import { obtenerResumenLiga, sondearLiga, type ResumenLiga } from '../api/liga'
import { BotonRefresco } from '../componentes/BotonRefresco'
import { TablaClasificacion } from '../componentes/liga/TablaClasificacion'
import { VistaClan } from '../componentes/liga/VistaClan'
import { VistaRondas } from '../componentes/liga/VistaRondas'

type Pestana = 'grupo' | 'rondas' | 'clan'

/** Las mismas tres pestañas que muestra el juego en la pantalla de la liga. */
const PESTANAS: { clave: Pestana; etiqueta: string }[] = [
  { clave: 'grupo', etiqueta: 'Grupo' },
  { clave: 'rondas', etiqueta: 'Rondas' },
  { clave: 'clan', etiqueta: 'Clan' },
]

export function PaginaLiga() {
  const [resumen, setResumen] = useState<ResumenLiga | null>(null)
  const [pestana, setPestana] = useState<Pestana>('clan')
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function cargar() {
    setCargando(true)
    setError(null)
    try {
      setResumen(await obtenerResumenLiga())
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
    await sondearLiga()
    await cargar()
  }

  const tagPropio = resumen?.clasificacion.find((c) => c.es_propio)?.tag

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-display text-xl font-bold">
          Liga de Guerras de Clanes
          {resumen?.temporada && (
            <span className="font-normal text-base-texto/70">
              {' — '}temporada {resumen.temporada}
              {resumen.ronda_actual !== null && <> · Ronda actual: {resumen.ronda_actual}/{resumen.total_rondas}</>}
            </span>
          )}
        </h2>
        <BotonRefresco
          seccion="liga"
          alActualizar={actualizar}
          className="border-liga-borde bg-liga-panel text-liga-texto hover:brightness-95"
        />
      </div>

      {error && (
        <p className="rounded-lg border-2 border-red-300 bg-red-50 px-4 py-2 text-red-700">{error}</p>
      )}
      {cargando && <p>Cargando…</p>}

      {!cargando && !error && resumen && resumen.rondas.length === 0 && (
        <div className="rounded-2xl border-4 border-liga-borde bg-liga-fondo p-6 text-liga-texto">
          Todavía no hay ninguna liga guardada. Si tu clan está en una, usa el botón Actualizar para traerla.
        </div>
      )}

      {!cargando && !error && resumen && resumen.rondas.length > 0 && (
        <div className="space-y-4 rounded-2xl border-4 border-liga-borde bg-liga-fondo p-6 text-liga-texto">
          <div className="flex gap-2">
            {PESTANAS.map((p) => (
              <button
                key={p.clave}
                type="button"
                onClick={() => setPestana(p.clave)}
                className={`rounded-t-lg border-2 border-b-0 px-5 py-2 font-display font-bold transition ${
                  pestana === p.clave
                    ? 'border-liga-borde bg-liga-panel'
                    : 'border-transparent bg-liga-borde/20 hover:bg-liga-borde/35'
                }`}
              >
                {p.etiqueta}
              </button>
            ))}
          </div>

          {pestana === 'grupo' && <TablaClasificacion clasificacion={resumen.clasificacion} />}
          {pestana === 'rondas' && (
            <VistaRondas
              enfrentamientos={resumen.enfrentamientos}
              totalRondas={resumen.total_rondas}
              tagPropio={tagPropio}
            />
          )}
          {pestana === 'clan' && <VistaClan resumen={resumen} />}
        </div>
      )}
    </section>
  )
}