import { ChangeEvent, FormEvent, useEffect, useState } from "react";

type ProviderId = "openai" | "openrouter" | "llama_cpp";
type ContractType = "auto" | "sale" | "labor" | "lease";

type ProviderState = {
  provider: ProviderId;
  label: string;
  configured: boolean;
  api_key_mask: string | null;
  base_url: string;
  model: string;
};

type ReviewResponse = {
  markdown: string;
  contract_type: string;
  contract_type_label: string;
  risk_level: string;
  risk_themes: string[];
  related_articles: Array<{
    citation: string;
    source_url: string;
  }>;
};

const CONTRACT_TYPES: Array<{ value: ContractType; label: string }> = [
  { value: "auto", label: "自動判斷" },
  { value: "sale", label: "買賣合約" },
  { value: "labor", label: "勞動合約" },
  { value: "lease", label: "租賃合約" },
];

const PROVIDERS: Array<{ value: ProviderId; label: string }> = [
  { value: "openai", label: "OpenAI" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "llama_cpp", label: "llama.cpp" },
];

function App() {
  const [providers, setProviders] = useState<ProviderState[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<ProviderId>("openai");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [contractType, setContractType] = useState<ContractType>("auto");
  const [contractText, setContractText] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [useLlm, setUseLlm] = useState(false);
  const [result, setResult] = useState<ReviewResponse | null>(null);
  const [status, setStatus] = useState("尚未審查");
  const [loading, setLoading] = useState(false);

  const currentProvider = providers.find((item) => item.provider === selectedProvider);

  useEffect(() => {
    void refreshSettings();
  }, []);

  useEffect(() => {
    if (currentProvider) {
      setBaseUrl(currentProvider.base_url);
      setModel(currentProvider.model);
      setApiKey("");
    }
  }, [currentProvider?.provider]);

  async function refreshSettings() {
    const response = await fetch("/api/settings");
    const data = await response.json();
    setProviders(data.providers);
  }

  async function saveProvider(event: FormEvent) {
    event.preventDefault();
    setStatus("正在保存 API 設定...");
    const response = await fetch("/api/settings/provider", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: selectedProvider,
        api_key: apiKey,
        base_url: baseUrl,
        model,
      }),
    });
    if (!response.ok) {
      setStatus("API 設定保存失敗");
      return;
    }
    await refreshSettings();
    setApiKey("");
    setStatus("API 設定已保存");
  }

  async function clearProvider() {
    setStatus("正在清除 API key...");
    const response = await fetch(`/api/settings/provider/${selectedProvider}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      setStatus("API key 清除失敗");
      return;
    }
    await refreshSettings();
    setStatus("API key 已清除");
  }

  async function submitReview(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setStatus("正在產生審查報告...");
    const formData = new FormData();
    formData.set("text", contractText);
    formData.set("contract_type", contractType);
    formData.set("provider", selectedProvider);
    formData.set("model", model);
    formData.set("base_url", baseUrl);
    formData.set("use_llm", String(useLlm));
    if (selectedFile) {
      formData.set("file", selectedFile);
    }

    const response = await fetch("/api/review", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    setLoading(false);
    if (!response.ok) {
      setStatus(data.detail || "審查失敗");
      return;
    }
    setResult(data);
    setStatus("審查完成");
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    setSelectedFile(event.target.files?.[0] ?? null);
  }

  async function copyReport() {
    if (!result) return;
    await navigator.clipboard.writeText(result.markdown);
    setStatus("已複製 Markdown 報告");
  }

  function downloadReport() {
    if (!result) return;
    const blob = new Blob([result.markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "contract-review-report.md";
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">Local Taiwan Contract Review Agent</p>
        <h1>台灣合約審查 Agent</h1>
        <p>
          以本地 SQLite 法條與規則為基礎，可選擇 API 模型產生 Markdown
          審查報告。API key 僅保存於本機 .env。
        </p>
      </section>

      <section className="panel grid-two">
        <form onSubmit={saveProvider} className="card">
          <h2>API 設定</h2>
          <label>
            模型供應商
            <select
              value={selectedProvider}
              onChange={(event) => setSelectedProvider(event.target.value as ProviderId)}
            >
              {PROVIDERS.map((provider) => (
                <option key={provider.value} value={provider.value}>
                  {provider.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            API key
            <input
              type="password"
              value={apiKey}
              placeholder={
                currentProvider?.configured
                  ? `已設定 ${currentProvider.api_key_mask}`
                  : "貼上 API key"
              }
              onChange={(event) => setApiKey(event.target.value)}
            />
          </label>
          <label>
            Base URL
            <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
          </label>
          <label>
            模型名稱
            <input value={model} onChange={(event) => setModel(event.target.value)} />
          </label>
          <div className="button-row">
            <button type="submit">保存設定</button>
            <button type="button" className="ghost" onClick={clearProvider}>
              清除 key
            </button>
          </div>
        </form>

        <form onSubmit={submitReview} className="card review-form">
          <h2>合約輸入</h2>
          <label>
            合約模式
            <select
              value={contractType}
              onChange={(event) => setContractType(event.target.value as ContractType)}
            >
              {CONTRACT_TYPES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            TXT 上傳
            <input type="file" accept=".txt,text/plain" onChange={onFileChange} />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={useLlm}
              onChange={(event) => setUseLlm(event.target.checked)}
            />
            使用 API 模型產生報告；未勾選時使用本地 dry-run 報告。
          </label>
          <label>
            合約文字
            <textarea
              value={contractText}
              onChange={(event) => setContractText(event.target.value)}
              placeholder="貼上合約全文，或上傳 .txt 檔。"
            />
          </label>
          <button type="submit" disabled={loading}>
            {loading ? "審查中..." : "產生審查報告"}
          </button>
        </form>
      </section>

      <section className="panel result-panel">
        <div className="result-heading">
          <div>
            <p className="eyebrow">Status</p>
            <h2>{status}</h2>
          </div>
          <div className="button-row">
            <button type="button" className="ghost" onClick={copyReport} disabled={!result}>
              複製
            </button>
            <button type="button" className="ghost" onClick={downloadReport} disabled={!result}>
              下載 .md
            </button>
          </div>
        </div>
        {result ? (
          <>
            <div className="summary-strip">
              <span>{result.contract_type_label}</span>
              <span>{result.risk_level}</span>
              <span>{result.related_articles.length} 個法條引用</span>
            </div>
            <pre className="markdown-preview">{result.markdown}</pre>
          </>
        ) : (
          <p className="empty-state">設定模型、輸入合約後，審查報告會顯示在這裡。</p>
        )}
      </section>
    </main>
  );
}

export default App;
