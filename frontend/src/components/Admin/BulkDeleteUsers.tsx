import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"
import { useState } from "react"

import { UsersService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

interface BulkDeleteUsersProps {
  selectedUserIds: string[]
  onSuccess: () => void
}

const BulkDeleteUsers = ({
  selectedUserIds,
  onSuccess,
}: BulkDeleteUsersProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const mutation = useMutation({
    mutationFn: async () => {
      await UsersService.bulkDeleteUsers({
        body: { user_ids: selectedUserIds },
      })
    },
    onSuccess: async () => {
      showSuccessToast("Users deleted successfully")
      onSuccess()
      await queryClient.invalidateQueries({ queryKey: ["users"] })
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => setIsOpen(false),
  })

  const count = selectedUserIds.length

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <Button
        variant="destructive"
        disabled={count === 0}
        onClick={() => setIsOpen(true)}
      >
        <Trash2 />
        Delete User(s)
      </Button>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Delete users</DialogTitle>
          <DialogDescription>
            {count} {count === 1 ? "user" : "users"} will be deleted. All Items
            associated with these users will also be{" "}
            <strong>permanently deleted.</strong> You will not be able to undo
            this action.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="mt-4">
          <DialogClose asChild>
            <Button variant="outline" disabled={mutation.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <LoadingButton
            aria-label="Delete users"
            variant="destructive"
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            Delete users
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default BulkDeleteUsers
