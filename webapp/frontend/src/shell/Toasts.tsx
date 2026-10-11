import { useStore } from "./hooks";
import { Icon, type IconName } from "./icons";
import { dismissToast, toasts, type ToastKind } from "./telemetry";

const ICON: Record<ToastKind, IconName> = { info: "info", ok: "check", warn: "alert", error: "alert" };

export default function Toasts() {
  const list = useStore(toasts);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {list.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`}>
          <Icon name={ICON[t.kind]} />
          <div className="toast-body">
            <div className="toast-title">{t.title}</div>
            {t.detail && <div className="toast-detail">{t.detail}</div>}
          </div>
          <button className="icon-btn" aria-label="dismiss" onClick={() => dismissToast(t.id)}>
            <Icon name="x" size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
