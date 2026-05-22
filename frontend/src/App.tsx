import { Routes, Route, Navigate } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { ProjectListPage } from '@/pages/ProjectListPage'
import { NewProjectPage } from '@/pages/NewProjectPage'
import { ProjectDetailPage } from '@/pages/ProjectDetailPage'
import { ChatPage } from '@/pages/ChatPage'

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        {/* Redirect root to /projects */}
        <Route index element={<Navigate to="/projects" replace />} />

        {/* Project routes */}
        <Route path="/projects" element={<ProjectListPage />} />
        <Route path="/projects/new" element={<NewProjectPage />} />
        <Route path="/projects/:id" element={<ProjectDetailPage />} />
        <Route path="/projects/:id/chat" element={<ChatPage />} />

        {/* Catch-all */}
        <Route path="*" element={<Navigate to="/projects" replace />} />
      </Route>
    </Routes>
  )
}
