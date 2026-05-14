import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { RefreshCw } from "lucide-react";

import { fetchAuthChallenge, loginAccount, registerAccount, resendVerification, verifyEmail } from "../../api";
import type { AuthChallengeProof, AuthChallengePurpose, AuthChallengeResponse, AuthUser } from "../../types";
import { DEFAULT_THEME, type UiThemeId } from "../../themes";
import { ThemeArtifacts } from "../ThemeArtifacts";

function SliderPuzzleModalChallenge({
  purpose,
  disabled,
  onVerified,
  onCancel
}: {
  purpose: AuthChallengePurpose;
  disabled?: boolean;
  onVerified: (proof: AuthChallengeProof) => void;
  onCancel: () => void;
}) {
  const [challenge, setChallenge] = useState<AuthChallengeResponse | null>(null);
  const [position, setPosition] = useState(0);
  const [state, setState] = useState<"loading" | "ready" | "checking" | "verified" | "error">("loading");
  const [message, setMessage] = useState("正在载入拼图...");
  const [reloadNonce, setReloadNonce] = useState(0);
  const startedAtRef = useRef(Date.now());
  const positionRef = useRef(0);
  const verifyingRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    setChallenge(null);
    positionRef.current = 0;
    verifyingRef.current = false;
    setPosition(0);
    setState("loading");
    setMessage("正在载入拼图...");
    fetchAuthChallenge(purpose)
      .then((nextChallenge) => {
        if (cancelled) return;
        startedAtRef.current = Date.now();
        setChallenge(nextChallenge);
        positionRef.current = 0;
        verifyingRef.current = false;
        setPosition(0);
        if (nextChallenge.algorithm !== "slider-puzzle-v1") {
          setState("error");
          setMessage("当前后端仍在使用旧版校验，请刷新页面或重启后端。");
          return;
        }
        setState("ready");
        setMessage(nextChallenge.prompt || "拖动拼图到缺口处。");
      })
      .catch((challengeError) => {
        if (cancelled) return;
        setState("error");
        setMessage(challengeError instanceof Error ? challengeError.message : "人机校验载入失败，请刷新后重试。");
      });
    return () => {
      cancelled = true;
    };
  }, [purpose, reloadNonce]);

  const trackWidth = challenge?.slider_track_width ?? 320;
  const stageHeight = 150;
  const pieceSize = challenge?.slider_piece_size ?? 46;
  const targetX = challenge?.slider_target_x ?? Math.round(trackWidth * 0.58);
  const targetY = challenge?.slider_target_y ?? 52;
  const tolerance = challenge?.slider_tolerance ?? 8;
  const imageUrl = challenge?.slider_image_url ?? "/auth_captcha/notebook-paper.jpg";
  const imageLabel = challenge?.slider_image_label ?? "拼图图片";
  const decoys = challenge?.slider_decoys ?? [];
  const maxPosition = Math.max(1, trackWidth - pieceSize);

  function clampPosition(nextPosition: number) {
    return Math.max(0, Math.min(maxPosition, nextPosition));
  }

  function setSliderPosition(nextPosition: number) {
    const clampedPosition = clampPosition(nextPosition);
    positionRef.current = clampedPosition;
    setPosition(clampedPosition);
  }

  function resetSlider() {
    verifyingRef.current = false;
    setReloadNonce((current) => current + 1);
  }

  async function verifySlider(releasedPosition = positionRef.current) {
    if (!challenge || challenge.algorithm !== "slider-puzzle-v1" || disabled || state !== "ready" || verifyingRef.current) {
      return;
    }
    const answerPosition = Math.round(releasedPosition);
    setSliderPosition(answerPosition);
    verifyingRef.current = true;
    if (Math.abs(answerPosition - targetX) > tolerance) {
      setState("error");
      setMessage("没有对准，正在换一张图...");
      window.setTimeout(() => {
        verifyingRef.current = false;
        setReloadNonce((current) => current + 1);
      }, 260);
      return;
    }
    setState("checking");
    setMessage("拼图已对齐，正在确认...");
    const elapsed = Date.now() - startedAtRef.current;
    const remaining = Math.max(0, challenge.min_elapsed_ms - elapsed);
    if (remaining > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, remaining));
    }
    setState("verified");
    setMessage("校验通过，正在继续...");
    onVerified({
      challenge_id: challenge.challenge_id,
      challenge_nonce: challenge.nonce,
      challenge_answer: answerPosition,
      challenge_elapsed_ms: Date.now() - startedAtRef.current
    });
  }

  function handleRangeRelease() {
    if (disabled || state !== "ready" || verifyingRef.current) return;
    void verifySlider(positionRef.current);
  }

  return (
    <div className={`authPuzzle authPuzzle-${state}`}>
      <div className="authPuzzleHeader">
        <div>
          <span>拖动滑块完成拼图校验</span>
          <small>松开后自动校验，失败会换一张图</small>
        </div>
        <button type="button" onClick={resetSlider} disabled={disabled || state === "loading"}>
          换一张
        </button>
      </div>
      <div
        className="authPuzzleStage"
        aria-label={imageLabel}
        style={{
          width: `${trackWidth}px`,
          height: `${stageHeight}px`,
          backgroundImage: `linear-gradient(rgba(20, 20, 20, 0.08), rgba(20, 20, 20, 0.08)), url(${imageUrl})`,
          backgroundSize: `${trackWidth}px ${stageHeight}px`,
          backgroundPosition: "center"
        }}
      >
        <div
          className="authPuzzleGap"
          style={{ left: `${targetX}px`, top: `${targetY}px`, width: `${pieceSize}px`, height: `${pieceSize}px` }}
        />
        {decoys.map((decoy, index) => (
          <div
            // eslint-disable-next-line react/no-array-index-key
            key={`${decoy.x}-${decoy.y}-${index}`}
            className="authPuzzleGap authPuzzleGapDecoy"
            style={{ left: `${decoy.x}px`, top: `${decoy.y}px`, width: `${pieceSize}px`, height: `${pieceSize}px` }}
          />
        ))}
        <div
          className="authPuzzlePiece"
          aria-hidden="true"
          style={{
            left: `${position}px`,
            top: `${targetY}px`,
            width: `${pieceSize}px`,
            height: `${pieceSize}px`,
            backgroundImage: `url(${imageUrl})`,
            backgroundSize: `${trackWidth}px ${stageHeight}px`,
            backgroundPosition: `-${targetX}px -${targetY}px`
          }}
        />
      </div>
      <div className="authPuzzleSliderWrap">
        <input
          type="range"
          min={0}
          max={maxPosition}
          step={1}
          value={Math.round(position)}
          aria-label="拖动滑块完成拼图校验"
          disabled={disabled || state !== "ready"}
          onChange={(event) => setSliderPosition(Number(event.currentTarget.value))}
          onPointerUp={handleRangeRelease}
          onMouseUp={handleRangeRelease}
          onTouchEnd={handleRangeRelease}
          onKeyUp={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              handleRangeRelease();
            }
          }}
        />
      </div>
      <div className="authPuzzleFooter">
        <p>{message}</p>
      </div>
      <button type="button" className="authPuzzleCancel" onClick={onCancel} disabled={disabled || state === "checking"}>
        取消
      </button>
    </div>
  );
}

export function AuthGateway({
  onAuthenticated,
  theme = DEFAULT_THEME
}: {
  onAuthenticated: (token: string, user: AuthUser) => void;
  theme?: UiThemeId;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [loginName, setLoginName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [code, setCode] = useState("");
  const [website, setWebsite] = useState("");
  const [verificationSent, setVerificationSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [captchaPurpose, setCaptchaPurpose] = useState<AuthChallengePurpose | null>(null);
  const pendingAuthActionRef = useRef<"login" | "register" | "resend" | null>(null);

  const isRegister = mode === "register";

  function openCaptcha(kind: "login" | "register" | "resend", purpose: AuthChallengePurpose) {
    pendingAuthActionRef.current = kind;
    setCaptchaPurpose(purpose);
    setNotice("");
    setError("");
  }

  function closeCaptcha() {
    pendingAuthActionRef.current = null;
    setCaptchaPurpose(null);
  }

  function switchMode(nextMode: "login" | "register") {
    setMode(nextMode);
    setNotice("");
    setError("");
    closeCaptcha();
    if (nextMode === "login") {
      setPassword("");
      setConfirmPassword("");
      setCode("");
      setVerificationSent(false);
    }
  }

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice("");
    setError("");
    if (mode === "login") {
      openCaptcha("login", "login");
      return;
    }
    if (password !== confirmPassword) {
      setError("两次输入的密码不一致。");
      return;
    }
    if (!verificationSent) {
      openCaptcha("register", "register");
      return;
    }
    setBusy(true);
    try {
      await verifyEmail({ email, code });
      setLoginName(email);
      setPassword("");
      setConfirmPassword("");
      setCode("");
      setVerificationSent(false);
      setMode("login");
      setNotice("账号已激活，请登录。");
    } catch (authError) {
      setError(authError instanceof Error ? authError.message : "认证请求失败。");
    } finally {
      setBusy(false);
    }
  }

  async function resendCode() {
    if (!email.trim()) return;
    openCaptcha("resend", "resend_verification");
  }

  async function runAuthAction(kind: "login" | "register" | "resend", proof: AuthChallengeProof) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      if (kind === "login") {
        const result = await loginAccount({ login: loginName, password, website, challenge: proof });
        onAuthenticated(result.token, result.user);
        return;
      }
      if (kind === "register") {
        const result = await registerAccount({ email, username, password, website, challenge: proof });
        setVerificationSent(true);
        setNotice(result.message || "验证码已发送，请查收邮箱。");
        return;
      }
      const result = await resendVerification(email, website, proof);
      setNotice(result.message || "新的验证码已发送。");
      setVerificationSent(true);
    } catch (authError) {
      setError(authError instanceof Error ? authError.message : "认证请求失败。");
    } finally {
      closeCaptcha();
      setBusy(false);
    }
  }

  function handleCaptchaVerified(proof: AuthChallengeProof) {
    const action = pendingAuthActionRef.current;
    if (!action) {
      closeCaptcha();
      return;
    }
    void runAuthAction(action, proof);
  }

  return (
    <main className={`authShell surfaceTransition theme-${theme}`}>
      <ThemeArtifacts theme={theme} />
      <section className="authPanel authPanelRefined">
        <div className="authEditorial authEditorialRefined">
          <h1>{"Web\u865a\u62df\u5206\u8eab"}</h1>
          <p>
            {"\u4e3a\u4efb\u4f55\u4eba\u521b\u5efa\u865a\u62df\u5206\u8eab\uff0c\u4ece\u672c\u9879\u76ee\u4f5c\u8005\u8fd9\u6837\u7684\u65e0\u540d\u5c0f\u5352\u5230\u540d\u6ee1\u5929\u4e0b\u7684\u4eba\u7c7b\u7fa4\u661f"}
          </p>
        </div>
        <form className="authForm authFormRefined" onSubmit={(event) => void submitAuth(event)}>
          <div className="authFormHeader">
            <p className="authKicker">{isRegister ? "注册" : "登录"}</p>
            <h2>{isRegister ? "注册账户" : "登录账户"}</h2>
            <span>{isRegister ? "验证码会发送到你的邮箱。" : "使用管理员或普通用户账号继续。"}</span>
          </div>

          {isRegister ? (
            <>
              <label>
                邮箱
                <input
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  disabled={verificationSent}
                />
              </label>
              <label>
                用户名
                <input
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  autoComplete="username"
                  disabled={verificationSent}
                />
              </label>
              <label>
                密码
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="new-password"
                  disabled={verificationSent}
                />
              </label>
              <label>
                确认密码
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  autoComplete="new-password"
                  disabled={verificationSent}
                />
              </label>
              {verificationSent ? (
                <div className="authVerificationPanel">
                  <label>
                    邮箱验证码
                    <input value={code} onChange={(event) => setCode(event.target.value)} inputMode="numeric" />
                  </label>
                  <button type="button" className="authTextButton" disabled={busy} onClick={() => void resendCode()}>
                    没收到？重发验证码
                  </button>
                </div>
              ) : null}
            </>
          ) : (
            <>
              <label>
                账号
                <input value={loginName} onChange={(event) => setLoginName(event.target.value)} autoComplete="username" />
              </label>
              <label>
                密码
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                />
              </label>
            </>
          )}

          {notice ? <p className="authNotice">{notice}</p> : null}
          {error ? <p className="authError">{error}</p> : null}
          <label className="authHoneypot" aria-hidden="true">
            主页
            <input
              value={website}
              onChange={(event) => setWebsite(event.target.value)}
              tabIndex={-1}
              autoComplete="off"
            />
          </label>

          <div className="authActions">
            <button
              type="submit"
              className="primaryButton"
              disabled={busy}
            >
              {busy ? "处理中" : isRegister ? (verificationSent ? "激活账号" : "发送验证码") : "进入系统"}
            </button>
          </div>

          <p className="authLinkRow">
            {isRegister ? "已有账户？" : "没有账户？"}
            <button type="button" onClick={() => switchMode(isRegister ? "login" : "register")}>
              {isRegister ? "登录" : "注册"}
            </button>
          </p>
        </form>
      </section>
      {captchaPurpose ? (
        <div className="authPuzzleOverlay" role="presentation" onMouseDown={closeCaptcha}>
          <section
            className="authPuzzleModal"
            role="dialog"
            aria-modal="true"
            aria-label="拖动拼图完成登录校验"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <SliderPuzzleModalChallenge
              purpose={captchaPurpose}
              disabled={busy}
              onVerified={handleCaptchaVerified}
              onCancel={closeCaptcha}
            />
          </section>
        </div>
      ) : null}
    </main>
  );
}

