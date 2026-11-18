import { STATUS_ICON, STATUS_LABEL } from "../format";
import type { SiteStatus } from "../types";

export function StatusBadge({ status }: { status: SiteStatus }) {
  return (
    <span className={`status ${status}`}>
      <span className="icon" aria-hidden>
        {STATUS_ICON[status]}
      </span>
      {STATUS_LABEL[status]}
    </span>
  );
}
