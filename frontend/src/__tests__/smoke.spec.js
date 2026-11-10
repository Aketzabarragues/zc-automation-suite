import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import App from "../App.vue";

describe("App", () => {
  it("monta el shell", () => {
    const wrapper = mount(App);
    expect(wrapper.text()).toContain("ZC Automation Suite");
  });
});
