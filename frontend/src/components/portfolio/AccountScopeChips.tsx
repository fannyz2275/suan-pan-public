import { useEffect, useState } from "react";
import api from "../../lib/api";

type Account = { id: string; name: string; type: string };

type Props = {
  selectedAccountId?: string;
  onChange: (accountId?: string) => void;
};

export default function AccountScopeChips({ selectedAccountId, onChange }: Props) {
  const [accounts, setAccounts] = useState<Account[]>([]);

  useEffect(() => {
    let cancelled = false;
    api.get<Account[]>("/finance/accounts").then((r) => {
      if (cancelled) return;
      setAccounts(r.data.filter((a) => a.type === "brokerage" || a.type === "retirement"));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const isAll = !selectedAccountId;
  return (
    <div className="flex flex-wrap gap-2 mb-3">
      <Chip active={isAll} testId="scope-chip-all" onClick={() => onChange(undefined)}>All investments</Chip>
      {accounts.map((a) => (
        <Chip
          key={a.id}
          active={selectedAccountId === a.id}
          testId={`scope-chip-${a.id}`}
          onClick={() => onChange(a.id)}
        >
          {a.name}
        </Chip>
      ))}
    </div>
  );
}

function Chip({
  active,
  testId,
  onClick,
  children,
}: {
  active: boolean;
  testId: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      data-testid={testId}
      aria-pressed={active}
      onClick={onClick}
      className={`px-3 py-1 text-sm rounded-full border ${
        active ? "bg-gray-900 text-white border-gray-900" : "bg-white text-gray-800 border-gray-300"
      }`}
    >
      {children}
    </button>
  );
}
