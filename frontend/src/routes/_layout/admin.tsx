import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import type { RowSelectionState } from "@tanstack/react-table"
import { Suspense, useState } from "react"

import { type UserPublic, UsersService } from "@/client"
import AddUser from "@/components/Admin/AddUser"
import BulkDeleteUsers from "@/components/Admin/BulkDeleteUsers"
import { columns, type UserTableData } from "@/components/Admin/columns"
import { DataTable } from "@/components/Common/DataTable"
import PendingUsers from "@/components/Pending/PendingUsers"
import useAuth from "@/hooks/useAuth"

function getUsersQueryOptions() {
  return {
    queryFn: async () =>
      (await UsersService.readUsers({ query: { skip: 0, limit: 100 } })).data,
    queryKey: ["users"],
  }
}

export const Route = createFileRoute("/_layout/admin")({
  component: Admin,
  beforeLoad: async () => {
    const { data: user } = await UsersService.readUserMe()
    if (!user.is_superuser) {
      throw redirect({
        to: "/",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "Admin - FastAPI Template",
      },
    ],
  }),
})

interface UsersTableContentProps {
  rowSelection: RowSelectionState
  onRowSelectionChange: React.Dispatch<React.SetStateAction<RowSelectionState>>
}

function UsersTableContent({
  rowSelection,
  onRowSelectionChange,
}: UsersTableContentProps) {
  const { user: currentUser } = useAuth()
  const { data: users } = useSuspenseQuery(getUsersQueryOptions())

  const tableData: UserTableData[] = users.data.map((user: UserPublic) => ({
    ...user,
    isCurrentUser: currentUser?.id === user.id,
  }))

  return (
    <DataTable
      columns={columns}
      data={tableData}
      rowSelection={rowSelection}
      onRowSelectionChange={onRowSelectionChange}
      getRowId={(user) => user.id}
      enableRowSelection={(row) => !row.original.isCurrentUser}
    />
  )
}

function UsersTable(props: UsersTableContentProps) {
  return (
    <Suspense fallback={<PendingUsers />}>
      <UsersTableContent {...props} />
    </Suspense>
  )
}

function Admin() {
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const selectedUserIds = Object.keys(rowSelection).filter(
    (id) => rowSelection[id],
  )

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Users</h1>
          <p className="text-muted-foreground">
            Manage user accounts and permissions
          </p>
        </div>
        <div className="flex items-center gap-2">
          <BulkDeleteUsers
            selectedUserIds={selectedUserIds}
            onSuccess={() => setRowSelection({})}
          />
          <AddUser />
        </div>
      </div>
      <UsersTable
        rowSelection={rowSelection}
        onRowSelectionChange={setRowSelection}
      />
    </div>
  )
}
