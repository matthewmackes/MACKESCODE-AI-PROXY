# Digital Ocean Serverless Inference Model Catalog Integration

## Overview
This document specifies the implementation of dynamic Digital Ocean Serverless Inference model catalog integration for the Matts Value Set Claude Code Proxy.

## Requirements Summary (from user answers)
1. **Model Source**: Digital Ocean API (dynamic fetch)
2. **API Design**: Endpoint parameter (`?available=true/false`)
3. **UI Selection**: Admin interface in web console
4. **Cost Tracking**: Auto-detect rates from Digital Ocean API
5. **Model Discovery**: Fetch at startup
6. **Backward Compatibility**: Replace hardcoded list with dynamic Digital Ocean list
7. **Error Handling**: Fall back to cached/last-known model list

## Technical Design

### 1. Digital Ocean API Client
```python
# Pseudo-code for Digital Ocean API client
class DigitalOceanModelsClient:
    def __init__(self, api_token=None):
        self.api_token = api_token or os.environ.get("DIGITALOCEAN_TOKEN")
        self.base_url = "https://api.digitalocean.com"
        self.cache_file = "~/.cache/matts-value-set/do-models-cache.json"
        self.cache_ttl = 3600  # 1 hour
    
    def fetch_available_models(self):
        """Fetch available models from Digital Ocean Serverless Inference API"""
        # Implementation details
        pass
    
    def fetch_model_pricing(self, model_id):
        """Fetch pricing information for a specific model"""
        pass
    
    def get_cached_models(self):
        """Get models from cache if available and not expired"""
        pass
```

### 2. Model Metadata Structure
```json
{
  "models": [
    {
      "id": "deepseek-3.2",
      "name": "DeepSeek V3.2",
      "provider": "DigitalOcean",
      "type": "text",  # "text" or "image"
      "context_window": 128000,
      "capabilities": ["chat", "completion"],
      "pricing": {
        "input_per_mtok": 0.27,
        "output_per_mtok": 1.1,
        "image_per_unit": 0.08
      },
      "enabled": true,
      "visible_in_ui": true,
      "last_updated": "2026-07-07T15:30:00Z"
    }
  ]
}
```

### 3. API Endpoint Changes
**Current**: `/v1/models` returns all models
**New**: `/v1/models?available=true` returns only enabled models
**New**: `/v1/models?available=false` returns all models (admin view)

```python
# Example implementation in do-anthropic-proxy.py
def handle_models_request(self):
    available_only = self.query_params.get("available", "true").lower() == "true"
    models = self.get_all_models()
    
    if available_only:
        models = [m for m in models if m.get("enabled", True)]
    
    return {
        "object": "list",
        "data": models,
        "metadata": {
            "total_count": len(models),
            "available_count": len([m for m in models if m.get("enabled", True)]),
            "fetched_at": datetime.now().isoformat()
        }
    }
```

### 4. Admin Interface Design
Add new admin section to web console:
- Model management panel
- Toggle visibility per model
- View model details and pricing
- Cache management controls

```html
<!-- Example admin panel -->
<div class="admin-panel" style="display: none;">
  <h2>Model Management</h2>
  <div class="model-list">
    <div class="model-item" v-for="model in allModels">
      <input type="checkbox" v-model="model.enabled">
      <span>{{ model.name }} ({{ model.id }})</span>
      <span class="cost">${{ model.pricing.input_per_mtok }}/M in, ${{ model.pricing.output_per_mtok }}/M out</span>
      <button @click="toggleVisibility(model)">Toggle UI</button>
    </div>
  </div>
  <button @click="refreshModels">Refresh from Digital Ocean</button>
  <button @click="saveConfig">Save Configuration</button>
</div>
```

### 5. Configuration System Integration
Add to configuration file (`config/models.yaml` or similar):
```yaml
models:
  enabled_models:
    - deepseek-3.2
    - deepseek-v4-pro
    - glm-5
  ui_visible_models:
    - deepseek-3.2
    - glm-5
  cache_ttl_seconds: 3600
  auto_refresh: true
```

### 6. Error Handling Strategy
1. **API failure**: Use cached model list
2. **Cache failure**: Use hardcoded fallback models
3. **Invalid model**: Skip and log error
4. **Rate limiting**: Implement exponential backoff

```python
def get_models_with_fallback(self):
    try:
        models = self.fetch_available_models()
        self.cache_models(models)
        return models
    except Exception as e:
        logger.warning(f"Failed to fetch models from Digital Ocean: {e}")
        cached = self.get_cached_models()
        if cached:
            return cached
        return self.get_hardcoded_models()  # Fallback to current list
```

## Implementation Steps

### Phase 1: Core Integration (2 hours)
1. Create Digital Ocean API client
2. Implement model caching system
3. Update `/v1/models` endpoint with filtering
4. Add fallback mechanisms

### Phase 2: Admin Interface (1 hour)
1. Add admin panel to web console
2. Implement model toggle controls
3. Add configuration persistence
4. Add refresh controls

### Phase 3: Cost Integration (1 hour)
1. Integrate pricing API
2. Update cost tracking system
3. Add pricing display
4. Update budget enforcement

## Files to Modify

### Primary:
- `do-anthropic-proxy.py` - API client and endpoint updates
- `image-studio.py` - Admin interface additions
- Configuration files - Model settings storage

### Secondary:
- `claude-DO.sh` - Model wrapper script updates
- `CLAUDE.md` - Documentation updates
- `README.md` - User documentation

## Dependencies
1. **Digital Ocean API access**: Requires valid API token
2. **Configuration system**: For model visibility settings (INT-004)
3. **Error handling**: For robust fallback (INT-003)

## Testing Strategy
1. **Unit tests**: API client, caching, filtering
2. **Integration tests**: Full endpoint testing
3. **UI tests**: Admin interface functionality
4. **Error scenario tests**: API failures, cache failures

## Migration from Hardcoded Models
1. Keep backward compatibility during transition
2. Add migration script for existing configurations
3. Document changes for users
4. Provide fallback to hardcoded list if needed

## Security Considerations
1. **API tokens**: Secure storage and rotation
2. **Admin access**: Authentication for model management
3. **Cache security**: Protect cached model data
4. **Rate limiting**: Prevent abuse of Digital Ocean API

## Monitoring and Logging
1. **Model fetch success/failure**: Log API calls
2. **Cache hits/misses**: Track caching effectiveness
3. **User model selections**: Analytics on model usage
4. **Error rates**: Monitor for issues

## Future Enhancements
1. **Model categories**: Group models by type/capability
2. **Performance metrics**: Track model performance
3. **Auto-enable new models**: Option to auto-enable new models
4. **Model recommendations**: Suggest models based on use case

## References
- Digital Ocean Serverless Inference API documentation
- Current model list in `do-anthropic-proxy.py`
- Existing cost tracking system
- Web console architecture

---
**Created**: 2026-07-07  
**Last Updated**: 2026-07-07  
**Related Task**: INT-015  
**Priority**: P1