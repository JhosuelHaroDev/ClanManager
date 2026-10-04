import { Route, Routes } from 'react-router-dom'
import { DisenoPrincipal } from './componentes/DisenoPrincipal'
import { PaginaGuerra } from './paginas/PaginaGuerra'
import { PaginaMiembros } from './paginas/PaginaMiembros'

function App() {
  return (
    <Routes>
      <Route element={<DisenoPrincipal />}>
        <Route path="/" element={<PaginaMiembros />} />
        <Route path="/guerra" element={<PaginaGuerra />} />
        {/* Las rutas de liga y asaltos se agregan junto con cada pantalla. */}
      </Route>
    </Routes>
  )
}

export default App