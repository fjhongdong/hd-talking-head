import {presenterIdentityAdapter} from "../production-input";
import type {ProductionInputAdapter} from "../production-input";

const base = presenterIdentityAdapter("host-shrink-to-chip", 91);

const adapt: ProductionInputAdapter = (brief, stagedMedia) => {
  const presenter = brief.media[0];
  if (!presenter || !Number.isInteger(presenter.width) || presenter.width <= 0 ||
      !Number.isInteger(presenter.height) || presenter.height <= 0) {
    throw new Error("[PRODUCTION_INPUT_INVALID] host-shrink-to-chip media geometry is invalid");
  }
  return base(brief, stagedMedia);
};

export default adapt;
