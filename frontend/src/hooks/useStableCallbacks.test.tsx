import { act, render } from "@testing-library/react";
import { memo, useState } from "react";
import { describe, expect, it } from "vitest";
import { useStableCallbacks } from "./useStableCallbacks";

describe("useStableCallbacks", () => {
  it("mantiene la identidad de los manejadores y siempre llama a la versión más reciente", () => {
    const seen: Array<() => void> = [];
    let renders = 0;
    const Child = memo(function Child({ onPing }: { onPing: () => void }) {
      renders += 1;
      seen.push(onPing);
      return <button type="button" onClick={onPing}>ping</button>;
    });
    const calls: number[] = [];
    let bump: () => void = () => undefined;
    function Parent() {
      const [count, setCount] = useState(0);
      bump = () => setCount((value) => value + 1);
      const { onPing } = useStableCallbacks({ onPing: () => { calls.push(count); } });
      return <Child onPing={onPing} />;
    }
    const { getByText } = render(<Parent />);
    act(() => bump());
    act(() => bump());
    expect(renders).toBe(1); // el hijo con memo no se repintó
    getByText("ping").click();
    expect(calls).toEqual([2]); // pero ve el estado actual (no el del primer render)
    expect(new Set(seen).size).toBe(1);
  });
});
