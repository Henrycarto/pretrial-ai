import { CohortBuilder } from "@/components/synthecore/CohortBuilder";
import { PageHeader } from "@/components/ui/AppShell";

export const metadata = { title: "New cohort" };

export default function NewCohortPage() {
  return (
    <>
      <PageHeader
        title="New cohort"
        subtitle="Upload a seed extract or generate against the reference population, then screen against the protocol."
      />
      <CohortBuilder />
    </>
  );
}
