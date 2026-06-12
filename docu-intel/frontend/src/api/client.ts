import { adminApi } from "./admin"
import { aiApi } from "./ai"
import { authApi } from "./auth"
import { businessApi } from "./business"
import { documentsApi } from "./documents"
import { integrationsApi } from "./integrations"
import { learningApi } from "./learning"
import { ocrFlowStreamUrl } from "./ocrFlow"
import { searchApi } from "./search"

export {
  ApiError,
  type BatchUploadResult,
  buildSearchParams,
  downloadUrl,
  pageImageUrl,
  request,
  thumbnailUrl,
} from "./core"

export { ocrFlowStreamUrl } from "./ocrFlow"

export const api = {
  ...authApi,
  ...adminApi,
  ...documentsApi,
  ...integrationsApi,
  ...searchApi,
  ...aiApi,
  ...businessApi,
  ...learningApi,
}
