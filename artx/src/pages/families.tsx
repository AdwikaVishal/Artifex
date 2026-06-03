import { useState } from 'react'
import { useFamilies, useCreateFamily, useUpdateFamily, useDeleteFamily } from '@/hooks/use-foster'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { Button } from '@/components/ui/button'
import { Input, Select, TextArea } from '@/components/ui/input'
import { Modal } from '@/components/ui/modal'
import { DataLoader } from '@/components/data-loader'
import { toast } from '@/components/ui/toast'
import { motion } from 'framer-motion'
import { Plus, Pencil, Trash2, Home, Users, MapPin, Globe, Shield, Dog } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Family, FamilyCreate, FamilyUpdate } from '@/types'

const emptyForm: FamilyCreate = {
  name: '',
  location: '',
  capacity: 1,
  experience: 'new',
  specializations: '',
  languages: '',
  special_needs_trained: false,
  accepts_siblings: false,
  emergency_available: false,
  max_age: 18,
  can_take_siblings: false,
  has_animals: false,
}

export default function FamiliesPage() {
  const { data: families, isLoading, error, refetch } = useFamilies()
  const createMutation = useCreateFamily()
  const updateMutation = useUpdateFamily()
  const deleteMutation = useDeleteFamily()

  const [showCreate, setShowCreate] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [form, setForm] = useState<FamilyCreate>(emptyForm)

  const editingFamily = editingId
    ? families?.find((f): f is Family => f.family_id === editingId) ?? null
    : null

  const resetForm = () => setForm(emptyForm)

  const handleCreate = async () => {
    try {
      await createMutation.mutateAsync(form)
      toast({ title: 'Family Created', description: `${form.name} added successfully`, variant: 'success' })
      setShowCreate(false)
      resetForm()
    } catch (err) {
      toast({ title: 'Error', description: 'Failed to create family', variant: 'error' })
    }
  }

  const handleUpdate = async () => {
    if (!editingId) return
    try {
      await updateMutation.mutateAsync({ familyId: editingId, data: form as FamilyUpdate })
      toast({ title: 'Family Updated', description: `${form.name} updated successfully`, variant: 'success' })
      setEditingId(null)
      resetForm()
    } catch (err) {
      toast({ title: 'Error', description: 'Failed to update family', variant: 'error' })
    }
  }

  const handleDelete = async () => {
    if (!deletingId) return
    try {
      await deleteMutation.mutateAsync(deletingId)
      toast({ title: 'Family Deleted', description: 'Foster home removed', variant: 'success' })
      setDeletingId(null)
    } catch (err) {
      toast({ title: 'Error', description: 'Failed to delete family', variant: 'error' })
    }
  }

  const openEdit = (family: Family) => {
    setForm({
      name: family.name,
      location: family.location,
      capacity: family.capacity,
      experience: family.experience,
      specializations: family.specializations,
      languages: family.languages,
      special_needs_trained: family.special_needs_trained,
      accepts_siblings: family.accepts_siblings,
      emergency_available: family.emergency_available,
      max_age: family.max_age,
      can_take_siblings: family.can_take_siblings,
      has_animals: family.has_animals,
    })
    setEditingId(family.family_id)
  }

  const isPending = createMutation.isPending || updateMutation.isPending

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Manage Families</h1>
          <p className="text-sm text-muted-foreground mt-1">Register and manage foster homes</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={() => refetch()}>
            Refresh
          </Button>
          <Button size="sm" onClick={() => { resetForm(); setShowCreate(true) }}>
            <Plus size={16} />
            Add Family
          </Button>
        </div>
      </div>

      <DataLoader isLoading={isLoading} error={error} type="table" rows={5}>
        {families && families.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {families.map((family, i) => (
              <motion.div
                key={family.family_id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.03 }}
              >
                <GlassCard hover className="relative">
                  <div className="absolute top-4 right-4 flex gap-1">
                    <button
                      onClick={() => openEdit(family)}
                      className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-glass-hover transition-colors cursor-pointer"
                      title="Edit"
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={() => setDeletingId(family.family_id)}
                      className="p-1.5 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors cursor-pointer"
                      title="Delete"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>

                  <div className="flex items-center gap-3 mb-3">
                    <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                      <Home size={20} className="text-primary" />
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold text-foreground">{family.name}</h3>
                      <span className="text-xs font-mono text-muted-foreground">{family.family_id}</span>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="flex items-center gap-1.5 text-muted-foreground">
                      <MapPin size={12} />
                      <span className="truncate">{family.location || 'No location'}</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-muted-foreground">
                      <Users size={12} />
                      <span>{family.available_capacity}/{family.capacity} available</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-muted-foreground">
                      <Shield size={12} />
                      <span>Max age: {family.max_age}</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-muted-foreground">
                      <Globe size={12} />
                      <span className="truncate">{family.languages || 'English'}</span>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-1.5 mt-3">
                    <span className={cn(
                      'px-2 py-0.5 rounded text-[10px] font-medium border',
                      family.experience === 'high' ? 'text-success border-success/30 bg-success/10' :
                      family.experience === 'medium' ? 'text-warning border-warning/30 bg-warning/10' :
                      'text-muted-foreground border-border-light bg-glass'
                    )}>
                      {family.experience}
                    </span>
                    {family.special_needs_trained && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium border border-primary/30 bg-primary/10 text-primary">
                        special needs
                      </span>
                    )}
                    {family.accepts_siblings && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium border border-info/30 bg-info/10 text-info">
                        siblings ok
                      </span>
                    )}
                    {family.emergency_available && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium border border-emergency/30 bg-emergency/10 text-emergency">
                        emergency
                      </span>
                    )}
                    {family.has_animals && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium border border-border-light bg-glass text-muted-foreground flex items-center gap-0.5">
                        <Dog size={10} /> pets
                      </span>
                    )}
                  </div>

                  {family.specializations && (
                    <p className="text-[11px] text-muted-foreground mt-2 line-clamp-2">{family.specializations}</p>
                  )}
                </GlassCard>
              </motion.div>
            ))}
          </div>
        ) : (
          <GlassCard>
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Home size={40} className="text-muted-foreground mb-3" />
              <h3 className="text-lg font-semibold text-foreground mb-1">No Families Registered</h3>
              <p className="text-sm text-muted-foreground mb-4">Add your first foster family to get started</p>
              <Button onClick={() => { resetForm(); setShowCreate(true) }}>
                <Plus size={16} />
                Add Family
              </Button>
            </div>
          </GlassCard>
        )}
      </DataLoader>

      {/* Create Modal */}
      <Modal
        open={showCreate}
        onClose={() => { setShowCreate(false); resetForm() }}
        title="Register New Foster Family"
        description="Enter the details of the foster home"
      >
        <FamilyForm form={form} onChange={setForm} />
        <div className="flex gap-3 justify-end mt-6">
          <Button variant="secondary" onClick={() => { setShowCreate(false); resetForm() }}>
            Cancel
          </Button>
          <Button onClick={handleCreate} loading={isPending}>
            <Plus size={16} />
            Create Family
          </Button>
        </div>
      </Modal>

      {/* Edit Modal */}
      <Modal
        open={!!editingId}
        onClose={() => { setEditingId(null); resetForm() }}
        title={`Edit ${editingFamily?.name || 'Family'}`}
        description="Update foster home details"
      >
        <FamilyForm form={form} onChange={setForm} />
        <div className="flex gap-3 justify-end mt-6">
          <Button variant="secondary" onClick={() => { setEditingId(null); resetForm() }}>
            Cancel
          </Button>
          <Button onClick={handleUpdate} loading={isPending}>
            <Pencil size={16} />
            Update Family
          </Button>
        </div>
      </Modal>

      {/* Delete Confirmation */}
      <Modal
        open={!!deletingId}
        onClose={() => setDeletingId(null)}
        title="Delete Family"
        description={`Are you sure you want to remove ${families?.find(f => f.family_id === deletingId)?.name || 'this family'}? This action cannot be undone.`}
      >
        <div className="flex gap-3 justify-end">
          <Button variant="secondary" onClick={() => setDeletingId(null)}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={handleDelete} loading={deleteMutation.isPending}>
            <Trash2 size={16} />
            Delete
          </Button>
        </div>
      </Modal>
    </motion.div>
  )
}

function FamilyForm({ form, onChange }: { form: FamilyCreate; onChange: (f: FamilyCreate) => void }) {
  const set = (key: keyof FamilyCreate, value: unknown) => onChange({ ...form, [key]: value })

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="col-span-2">
          <Input
            id="fam-name"
            label="Family Name"
            placeholder="e.g. The Johnson Family"
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
          />
        </div>
        <div className="col-span-2">
          <Input
            id="fam-location"
            label="Location"
            placeholder="e.g. 123 Main St, Springfield, IL"
            value={form.location}
            onChange={(e) => set('location', e.target.value)}
          />
        </div>
        <Input
          id="fam-capacity"
          label="Capacity"
          type="number"
          min={1}
          value={form.capacity}
          onChange={(e) => { const v = parseInt(e.target.value) || 1; set('capacity', v) }}
        />
        <Select
          id="fam-experience"
          label="Experience"
          value={form.experience}
          onChange={(e) => set('experience', e.target.value)}
          options={[
            { value: 'new', label: 'New' },
            { value: 'low', label: 'Low' },
            { value: 'medium', label: 'Medium' },
            { value: 'high', label: 'High' },
          ]}
        />
        <Input
          id="fam-max-age"
          label="Max Age"
          type="number"
          min={1}
          max={21}
          value={form.max_age}
          onChange={(e) => set('max_age', parseInt(e.target.value) || 18)}
        />
        <Input
          id="fam-languages"
          label="Languages"
          placeholder="e.g. English, Spanish"
          value={form.languages}
          onChange={(e) => set('languages', e.target.value)}
        />
        <div className="col-span-2">
          <TextArea
            id="fam-specializations"
            label="Specializations"
            placeholder="e.g. Therapeutic care, trauma-informed, adolescent support"
            value={form.specializations}
            onChange={(e) => set('specializations', e.target.value)}
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-4">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={form.special_needs_trained}
            onChange={(e) => set('special_needs_trained', e.target.checked)}
            className="w-4 h-4 rounded border-border-light bg-surface-alt accent-primary"
          />
          <span className="text-xs text-foreground">Special Needs Trained</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={form.accepts_siblings}
            onChange={(e) => set('accepts_siblings', e.target.checked)}
            className="w-4 h-4 rounded border-border-light bg-surface-alt accent-primary"
          />
          <span className="text-xs text-foreground">Accepts Siblings</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={form.emergency_available}
            onChange={(e) => set('emergency_available', e.target.checked)}
            className="w-4 h-4 rounded border-border-light bg-surface-alt accent-primary"
          />
          <span className="text-xs text-foreground">Emergency Available</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={form.can_take_siblings}
            onChange={(e) => set('can_take_siblings', e.target.checked)}
            className="w-4 h-4 rounded border-border-light bg-surface-alt accent-primary"
          />
          <span className="text-xs text-foreground">Can Take Siblings</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={form.has_animals}
            onChange={(e) => set('has_animals', e.target.checked)}
            className="w-4 h-4 rounded border-border-light bg-surface-alt accent-primary"
          />
          <span className="text-xs text-foreground">Has Pets</span>
        </label>
      </div>
    </div>
  )
}
