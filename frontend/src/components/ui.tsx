import {
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type PropsWithChildren,
} from "react";
import { XIcon, type Icon } from "@phosphor-icons/react";

export function Button({
  icon: IconComponent,
  variant = "neutral",
  children,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  icon?: Icon;
  variant?: "primary" | "neutral" | "subtle" | "danger";
}) {
  return (
    <button
      type="button"
      className={`button ${variant} ${className}`}
      {...props}
    >
      {IconComponent && <IconComponent size={20} aria-hidden="true" />}
      <span>{children}</span>
    </button>
  );
}
export function IconButton({
  icon: IconComponent,
  label,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { icon: Icon; label: string }) {
  return (
    <button
      type="button"
      className="icon-button"
      aria-label={label}
      title={label}
      {...props}
    >
      <IconComponent size={21} aria-hidden="true" />
    </button>
  );
}
export function Modal({
  title,
  onClose,
  children,
  footer,
}: PropsWithChildren<{
  title: string;
  onClose: () => void;
  footer?: React.ReactNode;
}>) {
  const titleId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => element.close();
  }, []);
  return (
    <dialog
      className="modal"
      ref={dialog}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <header>
        <h2 id={titleId}>{title}</h2>
        <IconButton label="关闭对话框" icon={XIcon} onClick={onClose} />
      </header>
      <div className="modal-body">{children}</div>
      {footer && <footer>{footer}</footer>}
    </dialog>
  );
}
