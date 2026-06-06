import { useState, useEffect } from 'react'
import { api } from '../lib/api'
import toast from 'react-hot-toast'
import {
  Phone, Mail, User, MapPin, Package, Search, Trash2, 
  ChevronLeft, ChevronRight, Filter, Download, RefreshCw,
  CheckCircle, AlertCircle, X
} from 'lucide-react'

interface Lead {
  id: string
  timestamp: string
  job_id: string
  job_name: string
  event_type: string
  keyword_matched: string
  product_title: string
  buyer_name: string
  buyer_phone: string
  buyer_email: string
  buyer_location: string
  buyer_address: string
  inquiry_message: string
  context_snippet: string
  page_url: string
  lead_fingerprint: string
  contact_revealed: string
  next_contact_retry_at: string
}

interface LeadsResponse {
  leads: Lead[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

interface LeadsStats {
  total: number
  with_phone: number
  with_email: number
  with_contact: number
  partial: number
  by_job: Record<string, number>
}

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([])
  const [stats, setStats] = useState<LeadsStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [contactOnly, setContactOnly] = useState(false)
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)

  const fetchLeads = async () => {
    setLoading(true)
    try {
      const params: Record<string, any> = { page, page_size: 25 }
      if (search) params.search = search
      if (contactOnly) params.contact_only = true
      
      const { data } = await api.get<LeadsResponse>('/leads', { params })
      setLeads(data.leads)
      setTotalPages(data.total_pages)
      setTotal(data.total)
    } catch (err) {
      toast.error('Failed to load leads')
    } finally {
      setLoading(false)
    }
  }

  const fetchStats = async () => {
    try {
      const { data } = await api.get<LeadsStats>('/leads/stats')
      setStats(data)
    } catch (err) {
      // ignore
    }
  }

  useEffect(() => {
    fetchLeads()
    fetchStats()
  }, [page, contactOnly])

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setPage(1)
    fetchLeads()
  }

  const handleDelete = async (leadId: string) => {
    if (!confirm('Delete this lead?')) return
    setDeleting(leadId)
    try {
      await api.delete(`/leads/${leadId}`)
      toast.success('Lead deleted')
      fetchLeads()
      fetchStats()
      if (selectedLead?.id === leadId) setSelectedLead(null)
    } catch (err) {
      toast.error('Failed to delete lead')
    } finally {
      setDeleting(null)
    }
  }

  const handleExportCSV = () => {
    // Create CSV from current leads
    const headers = ['Timestamp', 'Job', 'Keyword', 'Product', 'Name', 'Phone', 'Email', 'Location']
    const rows = leads.map(l => [
      l.timestamp,
      l.job_name,
      l.keyword_matched,
      l.product_title,
      l.buyer_name,
      l.buyer_phone,
      l.buyer_email,
      l.buyer_location
    ])
    
    const csv = [headers, ...rows].map(r => r.map(c => `"${(c || '').replace(/"/g, '""')}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `leads_export_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
    toast.success('CSV exported')
  }

  const formatDate = (ts: string) => {
    if (!ts) return '-'
    try {
      return new Date(ts).toLocaleString('en-IN', { 
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
      })
    } catch {
      return ts
    }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Captured Leads</h1>
          <p className="text-sm text-gray-400 mt-1">
            All buyer leads captured by automation
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => { fetchLeads(); fetchStats() }}
            className="flex items-center gap-2 px-3 py-2 text-sm bg-gray-800 text-gray-300 rounded-lg hover:bg-gray-700"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
          <button
            onClick={handleExportCSV}
            className="flex items-center gap-2 px-3 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-500"
          >
            <Download size={14} />
            Export CSV
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-xs text-gray-500 uppercase">Total Leads</p>
            <p className="text-2xl font-bold text-white mt-1">{stats.total}</p>
          </div>
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-xs text-gray-500 uppercase">With Phone</p>
            <p className="text-2xl font-bold text-green-400 mt-1">{stats.with_phone}</p>
          </div>
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-xs text-gray-500 uppercase">With Email</p>
            <p className="text-2xl font-bold text-blue-400 mt-1">{stats.with_email}</p>
          </div>
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-xs text-gray-500 uppercase">Complete</p>
            <p className="text-2xl font-bold text-emerald-400 mt-1">{stats.with_contact}</p>
          </div>
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-xs text-gray-500 uppercase">Partial</p>
            <p className="text-2xl font-bold text-yellow-400 mt-1">{stats.partial}</p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4">
        <form onSubmit={handleSearch} className="flex-1 min-w-[200px] max-w-md">
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name, phone, email, product..."
              className="w-full pl-10 pr-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
            />
          </div>
        </form>
        <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
          <input
            type="checkbox"
            checked={contactOnly}
            onChange={(e) => { setContactOnly(e.target.checked); setPage(1) }}
            className="w-4 h-4 rounded bg-gray-800 border-gray-600 text-blue-600 focus:ring-blue-500"
          />
          <Filter size={14} />
          With contact only
        </label>
      </div>

      {/* Leads Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-800/50">
              <tr>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase">Date</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase">Buyer</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase">Contact</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase">Product</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase">Location</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase">Status</th>
                <th className="text-right px-4 py-3 text-xs font-medium text-gray-400 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-500">
                    Loading...
                  </td>
                </tr>
              ) : leads.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-500">
                    No leads found
                  </td>
                </tr>
              ) : (
                leads.map((lead) => (
                  <tr 
                    key={lead.id} 
                    className="hover:bg-gray-800/50 cursor-pointer"
                    onClick={() => setSelectedLead(lead)}
                  >
                    <td className="px-4 py-3 text-gray-400 whitespace-nowrap">
                      {formatDate(lead.timestamp)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-full bg-blue-600/20 flex items-center justify-center">
                          <User size={14} className="text-blue-400" />
                        </div>
                        <span className="text-white font-medium">
                          {lead.buyer_name || '-'}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="space-y-1">
                        {lead.buyer_phone && (
                          <div className="flex items-center gap-1.5 text-green-400">
                            <Phone size={12} />
                            <span>{lead.buyer_phone}</span>
                          </div>
                        )}
                        {lead.buyer_email && (
                          <div className="flex items-center gap-1.5 text-blue-400">
                            <Mail size={12} />
                            <span className="truncate max-w-[150px]">{lead.buyer_email}</span>
                          </div>
                        )}
                        {!lead.buyer_phone && !lead.buyer_email && (
                          <span className="text-gray-500">-</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5 text-gray-300">
                        <Package size={12} className="text-gray-500" />
                        <span className="truncate max-w-[200px]">
                          {lead.product_title || lead.keyword_matched || '-'}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5 text-gray-400">
                        <MapPin size={12} className="text-gray-500" />
                        <span className="truncate max-w-[120px]">
                          {lead.buyer_location || '-'}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {lead.contact_revealed === 'true' ? (
                        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-green-500/10 text-green-400">
                          <CheckCircle size={10} />
                          Complete
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-yellow-500/10 text-yellow-400">
                          <AlertCircle size={10} />
                          Partial
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDelete(lead.id) }}
                        disabled={deleting === lead.id}
                        className="p-1.5 text-gray-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-800">
            <p className="text-sm text-gray-500">
              Showing {(page - 1) * 25 + 1} - {Math.min(page * 25, total)} of {total}
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="p-2 text-gray-400 hover:text-white disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronLeft size={16} />
              </button>
              <span className="text-sm text-gray-400">
                Page {page} of {totalPages}
              </span>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="p-2 text-gray-400 hover:text-white disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Lead Detail Modal */}
      {selectedLead && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
              <h2 className="text-lg font-semibold text-white">Lead Details</h2>
              <button
                onClick={() => setSelectedLead(null)}
                className="p-1 text-gray-400 hover:text-white"
              >
                <X size={20} />
              </button>
            </div>
            <div className="p-6 space-y-6">
              {/* Buyer Info */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-gray-500 uppercase mb-1">Buyer Name</p>
                  <p className="text-white font-medium">{selectedLead.buyer_name || '-'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 uppercase mb-1">Captured At</p>
                  <p className="text-gray-300">{formatDate(selectedLead.timestamp)}</p>
                </div>
              </div>

              {/* Contact */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-gray-500 uppercase mb-1">Phone</p>
                  {selectedLead.buyer_phone ? (
                    <a 
                      href={`tel:${selectedLead.buyer_phone}`}
                      className="flex items-center gap-2 text-green-400 hover:underline"
                    >
                      <Phone size={14} />
                      {selectedLead.buyer_phone}
                    </a>
                  ) : (
                    <p className="text-gray-500">Not available</p>
                  )}
                </div>
                <div>
                  <p className="text-xs text-gray-500 uppercase mb-1">Email</p>
                  {selectedLead.buyer_email ? (
                    <a 
                      href={`mailto:${selectedLead.buyer_email}`}
                      className="flex items-center gap-2 text-blue-400 hover:underline"
                    >
                      <Mail size={14} />
                      {selectedLead.buyer_email}
                    </a>
                  ) : (
                    <p className="text-gray-500">Not available</p>
                  )}
                </div>
              </div>

              {/* Location */}
              <div>
                <p className="text-xs text-gray-500 uppercase mb-1">Location / Address</p>
                <p className="text-gray-300">
                  {selectedLead.buyer_address || selectedLead.buyer_location || '-'}
                </p>
              </div>

              {/* Product */}
              <div>
                <p className="text-xs text-gray-500 uppercase mb-1">Product / Keyword</p>
                <p className="text-gray-300">
                  {selectedLead.product_title || selectedLead.keyword_matched || '-'}
                </p>
              </div>

              {/* Message */}
              {selectedLead.inquiry_message && (
                <div>
                  <p className="text-xs text-gray-500 uppercase mb-1">Inquiry Message</p>
                  <p className="text-gray-300 bg-gray-800 rounded-lg p-3 text-sm">
                    {selectedLead.inquiry_message}
                  </p>
                </div>
              )}

              {/* Meta */}
              <div className="grid grid-cols-2 gap-4 pt-4 border-t border-gray-800">
                <div>
                  <p className="text-xs text-gray-500 uppercase mb-1">Job</p>
                  <p className="text-gray-400 text-sm">{selectedLead.job_name}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 uppercase mb-1">Status</p>
                  {selectedLead.contact_revealed === 'true' ? (
                    <span className="inline-flex items-center gap-1 text-green-400 text-sm">
                      <CheckCircle size={12} />
                      Contact Revealed
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-yellow-400 text-sm">
                      <AlertCircle size={12} />
                      Partial (contact not revealed)
                    </span>
                  )}
                </div>
              </div>

              {/* Actions */}
              <div className="flex justify-end gap-3 pt-4 border-t border-gray-800">
                <button
                  onClick={() => handleDelete(selectedLead.id)}
                  className="flex items-center gap-2 px-4 py-2 text-sm text-red-400 hover:bg-red-500/10 rounded-lg"
                >
                  <Trash2 size={14} />
                  Delete Lead
                </button>
                <button
                  onClick={() => setSelectedLead(null)}
                  className="px-4 py-2 text-sm bg-gray-800 text-white rounded-lg hover:bg-gray-700"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
