import type { Enfrentamiento } from '../../api/liga'

const ETIQUETA_ESTADO_RONDA: Record<string, string> = {
  preparation: 'Preparación',
  inWar: 'En batalla',
  warEnded: 'Terminada',
}

/** Color de fondo de un lado del enfrentamiento: verde si ganó, rojo si perdió, neutro si no hay resultado. */
function colorLado(ganador: Enfrentamiento['ganador'], lado: 'a' | 'b'): string {
  if (ganador === null) return 'bg-white/60'
  if (ganador === 'empate') return 'bg-slate-200'
  return ganador === lado ? 'bg-emerald-200' : 'bg-rose-200'
}

/** Todas las guerras de cada ronda del grupo, no solo las de nuestro clan. */
export function VistaRondas({
  enfrentamientos,
  totalRondas,
  tagPropio,
}: {
  enfrentamientos: Enfrentamiento[]
  totalRondas: number
  tagPropio: string | undefined
}) {
  const numeros = Array.from({ length: totalRondas }, (_, i) => i + 1)

  return (
    <div className="space-y-4">
      {numeros.map((numero) => {
        const guerras = enfrentamientos.filter((e) => e.ronda === numero)
        return (
          <div key={numero} className="rounded-xl border-2 border-liga-borde bg-liga-panel p-3">
            <div className="mb-2 flex items-center justify-between">
              <h4 className="font-display text-lg font-bold">Ronda {numero}</h4>
              {guerras.length > 0 && (
                <span className="rounded-full border border-liga-borde px-2 py-0.5 text-xs font-semibold">
                  {ETIQUETA_ESTADO_RONDA[guerras[0].estado] ?? guerras[0].estado}
                </span>
              )}
            </div>

            {guerras.length === 0 ? (
              <p className="text-sm opacity-60">Aún sin emparejar</p>
            ) : (
              <div className="space-y-2">
                {guerras.map((g) => {
                  const esNuestra = tagPropio !== undefined && (g.clan_a_tag === tagPropio || g.clan_b_tag === tagPropio)
                  return (
                    <div
                      key={g.war_tag}
                      className={`grid grid-cols-[1fr_auto_1fr] overflow-hidden rounded-lg border ${
                        esNuestra ? 'border-2 border-liga-acento ring-2 ring-liga-acento/50' : 'border-liga-borde/50'
                      }`}
                    >
                      <div className={`flex items-center justify-between gap-2 px-3 py-2 ${colorLado(g.ganador, 'a')}`}>
                        <span className={`truncate font-semibold ${g.clan_a_tag === tagPropio ? 'underline' : ''}`}>
                          {g.clan_a_nombre}
                        </span>
                        <span className="font-bold">{g.clan_a_estrellas}⭐</span>
                      </div>
                      <div className="flex items-center bg-liga-fondo px-2 font-display text-xs font-bold">VS</div>
                      <div className={`flex items-center justify-between gap-2 px-3 py-2 ${colorLado(g.ganador, 'b')}`}>
                        <span className="font-bold">{g.clan_b_estrellas}⭐</span>
                        <span className={`truncate text-right font-semibold ${g.clan_b_tag === tagPropio ? 'underline' : ''}`}>
                          {g.clan_b_nombre}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}