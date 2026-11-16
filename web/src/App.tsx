import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { FileViewPage } from './pages/FileViewPage'
import { RepoMapPage } from './pages/RepoMapPage'
import { StartPage } from './pages/StartPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<StartPage />} />
        <Route path="/repo/:id" element={<RepoMapPage />} />
        <Route path="/repo/:id/file/*" element={<FileViewPage />} />
      </Routes>
    </BrowserRouter>
  )
}
