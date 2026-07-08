# Model Hero Card Feature Specification

## Overview
Create impressive, detailed Hero Cards for each AI model in the Matts Value Set Claude Code Proxy, providing users with clear guidance on what each model excels at, its limitations, typical use cases, and alternatives.

## Design Decisions (from user answers)
1. **Display Location**: Detailed modal (full-page overlay)
2. **Content Source**: Manual curation (well-written descriptions)
3. **Visual Style**: Feature-rich design (icons, badges, metrics)
4. **Information Sections**: Standard set (strengths, weaknesses, use cases, alternatives)
5. **Storage Strategy**: Separate JSON/YAML files

## Hero Card Design

### Visual Elements
1. **Hero Header**: Model name with provider badge
2. **Model Type Icon**: Text/Image model indicator
3. **Performance Metrics**: Context window, speed, accuracy indicators
4. **Cost Badge**: Price per million tokens
5. **Status Indicator**: Enabled/disabled, availability
6. **Quick Stats**: Brief stats in badge format

### Content Sections
1. **Strengths**: What this model excels at
2. **Weaknesses**: Areas where it struggles
3. **Use Cases**: Ideal applications and examples
4. **Alternatives**: Other models for different needs
5. **Technical Details**: Context window, training data, architecture
6. **Best Practices**: Tips for optimal use

## Implementation Details

### 1. JSON Description File Structure
```json
{
  "deepseek-3.2": {
    "name": "DeepSeek V3.2",
    "provider": "DigitalOcean",
    "type": "text",
    "description": "A highly efficient and capable model balancing performance and cost.",
    
    "hero_card": {
      "strengths": [
        "Excellent code generation and debugging",
        "Strong reasoning and problem-solving capabilities",
        "Cost-effective for general-purpose tasks",
        "Good at technical documentation"
      ],
      "weaknesses": [
        "Limited creative writing compared to larger models",
        "Shorter context window than premium models",
        "May struggle with highly specialized domain knowledge"
      ],
      "use_cases": [
        "Software development and coding assistance",
        "Technical documentation and explanations",
        "Data analysis and processing",
        "General Q&A and research"
      ],
      "alternatives": [
        {
          "model": "deepseek-v4-pro",
          "reason": "For higher accuracy and larger context needs"
        },
        {
          "model": "glm-5",
          "reason": "For Chinese language tasks"
        },
        {
          "model": "openai-gpt-5.3-codex",
          "reason": "For premium performance regardless of cost"
        }
      ],
      "technical_details": {
        "context_window": 128000,
        "architecture": "Transformer-based",
        "training_data": "Multilingual web, code, academic papers",
        "release_date": "2025"
      },
      "best_practices": [
        "Use for coding tasks where cost-effectiveness matters",
        "Ideal for iterative development and debugging",
        "Works well with clear, specific prompts",
        "Use temperature 0.7 for balanced creativity"
      ]
    },
    
    "visual_elements": {
      "color": "#1e88e5",
      "icon": "⚡",
      "badges": ["Fast", "Cost-effective", "Developer-friendly"]
    }
  }
}
```

### 2. Modal Design
```html
<!-- Modal structure -->
<div class="model-hero-modal" id="model-hero-modal">
  <div class="modal-overlay"></div>
  <div class="modal-content">
    <div class="modal-header">
      <h2 class="model-name">
        <span class="model-icon">{{icon}}</span>
        {{model_name}}
        <span class="provider-badge">{{provider}}</span>
      </h2>
      <button class="close-modal">&times;</button>
    </div>
    
    <div class="model-stats-bar">
      <div class="stat">
        <span class="stat-label">Context</span>
        <span class="stat-value">{{context_window}}k</span>
      </div>
      <div class="stat">
        <span class="stat-label">Cost</span>
        <span class="stat-value">${{input_cost}}/Min</span>
      </div>
      <div class="stat">
        <span class="stat-label">Type</span>
        <span class="stat-value">{{type}}</span>
      </div>
    </div>
    
    <div class="badges-container">
      {{#each badges}}
        <span class="model-badge">{{this}}</span>
      {{/each}}
    </div>
    
    <div class="content-sections">
      <section class="strengths">
        <h3><span class="icon">✅</span> Strengths</h3>
        <ul>
          {{#each strengths}}
            <li>{{this}}</li>
          {{/each}}
        </ul>
      </section>
      
      <section class="weaknesses">
        <h3><span class="icon">⚠️</span> Weaknesses</h3>
        <ul>
          {{#each weaknesses}}
            <li>{{this}}</li>
          {{/each}}
        </ul>
      </section>
      
      <section class="use-cases">
        <h3><span class="icon">🎯</span> Use Cases</h3>
        <ul>
          {{#each use_cases}}
            <li>{{this}}</li>
          {{/each}}
        </ul>
      </section>
      
      <section class="alternatives">
        <h3><span class="icon">🔄</span> Alternatives</h3>
        <div class="alternative-cards">
          {{#each alternatives}}
            <div class="alternative-card">
              <strong>{{model}}</strong>
              <p>{{reason}}</p>
              <button class="switch-model" data-model="{{model}}">
                Switch to {{model}}
              </button>
            </div>
          {{/each}}
        </div>
      </section>
    </div>
  </div>
</div>
```

### 3. API Endpoints
```python
# New endpoints in image-studio.py
@app.route('/api/models/<model_id>/info')
def get_model_info(model_id):
    """Get detailed hero card information for a model"""
    info = load_model_description(model_id)
    if not info:
        return jsonify({"error": "Model description not found"}), 404
    return jsonify(info)

@app.route('/api/models/info/all')
def get_all_model_info():
    """Get hero card information for all models"""
    all_info = {}
    for model_id in get_all_model_ids():
        info = load_model_description(model_id)
        if info:
            all_info[model_id] = info
    return jsonify(all_info)
```

### 4. UI Integration Points
1. **Model Selection Dropdown**: Info icon next to each model
2. **Chat Interface**: Model info button in header
3. **Image Studio**: Model info in generation settings
4. **Admin Panel**: Enhanced model management
5. **Keyboard Shortcut**: Ctrl+I for model info

## Implementation Phases

### Phase 1: Content Creation (1 hour)
1. Research each model's capabilities
2. Write detailed descriptions for all models
3. Create JSON description files
4. Add to configuration system

### Phase 2: Modal Implementation (1 hour)
1. Create modal HTML/CSS template
2. Implement JavaScript for modal interactions
3. Add API endpoints for model information
4. Integrate with existing template system

### Phase 3: UI Integration (0.5 hours)
1. Add info buttons throughout UI
2. Implement keyboard shortcuts
3. Add loading states and error handling
4. Test across all interface areas

## Files to Create/Modify

### New Files:
- `config/model-descriptions/` directory
- `config/model-descriptions/deepseek-3.2.json`
- `config/model-descriptions/deepseek-v4-pro.json`
- `config/model-descriptions/glm-5.json`
- `config/model-descriptions/mistral-3-14B.json`
- `config/model-descriptions/openai-gpt-5.3-codex.json`
- `config/model-descriptions/stable-diffusion-3.5-large.json`
- `templates/model-hero-modal.html`
- `static/css/model-hero.css`
- `static/js/model-hero.js`

### Modified Files:
- `image-studio.py` - Add API endpoints
- Existing templates - Add info buttons
- `CLAUDE.md` - Update documentation
- `MAIN-WORKLIST.md` - Track progress

## Visual Design Specifications

### Color Scheme:
- Primary color varies by model type
- Success green for strengths
- Warning orange for weaknesses
- Neutral gray for technical details
- Accent color for interactive elements

### Typography:
- Headers: 24px bold
- Section headers: 18px semi-bold
- Body text: 16px regular
- Small text: 14px regular

### Spacing:
- Modal padding: 24px
- Section margin: 16px
- Item spacing: 8px
- Badge spacing: 4px

### Icons and Badges:
- Use emoji or custom SVG icons
- Badges with subtle gradients
- Hover effects for interactivity
- Smooth transitions for modal

## Quality Standards

### Content Quality:
- Accurate technical information
- Helpful, actionable advice
- Clear, concise writing
- Consistent formatting

### Visual Quality:
- Responsive design (mobile/desktop)
- Accessible color contrast
- Smooth animations
- Consistent styling

### Technical Quality:
- Fast loading (cache descriptions)
- Error handling for missing data
- Keyboard navigation support
- Screen reader compatibility

## Testing Strategy

### Content Testing:
- Verify all model descriptions exist
- Check for accuracy and helpfulness
- Test alternative suggestions

### Functional Testing:
- Modal opens/closes correctly
- API endpoints return proper data
- Info buttons work in all locations
- Keyboard shortcuts function

### Visual Testing:
- Responsive design on all screen sizes
- Color contrast accessibility
- Animation performance
- Cross-browser compatibility

## Success Metrics
1. **User Engagement**: Info button click-through rate
2. **Content Quality**: User feedback on helpfulness
3. **Performance**: Modal load time < 100ms
4. **Accessibility**: WCAG 2.1 AA compliance
5. **Adoption**: Usage across different interface areas

---
**Related Task**: INT-017  
**Priority**: P1  
**Estimated Effort**: 2.5 hours  
**Dependencies**: INT-001 (Template separation)  
**Created**: 2026-07-08