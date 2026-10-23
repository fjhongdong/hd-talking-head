import {presenterIdentityAdapter} from "../production-input";
import type {ProductionInputAdapter} from "../production-input";

const base = presenterIdentityAdapter("word-relay-filmstrip", 163);

const adapt: ProductionInputAdapter = (brief, stagedMedia) => {
  const presenter = brief.media[0];
  if (!presenter || !Number.isInteger(presenter.width) || presenter.width <= 0 ||
      !Number.isInteger(presenter.height) || presenter.height <= 0) {
    throw new Error("[PRODUCTION_INPUT_INVALID] word-relay-filmstrip media geometry is invalid");
  }
  return base(brief, stagedMedia);
};

export default adapt;
