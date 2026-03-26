import Link from 'next/link'

import { Button } from '@/components/ui/button'

const nativeButton = (
  <Button type="submit" onClick={(event) => event.currentTarget.form?.requestSubmit()}>
    Save
  </Button>
)

const slottedButton = (
  <Button asChild>
    <Link href="/runs">Runs</Link>
  </Button>
)

void nativeButton
void slottedButton

export {}
